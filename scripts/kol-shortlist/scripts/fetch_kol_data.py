#!/usr/bin/env python3
"""
Fetch KOL Twitter data via APIDance API for shortlist generation.

Usage:
    python3 fetch_kol_data.py --handles "alice_web3,bob_defi,carol_nft" --output /tmp/kol_data.json

Requires APIDANCE_API_KEY environment variable.
"""

import argparse
import json
import os
import sys
import time
from datetime import datetime, timedelta, timezone

import requests

APIDANCE_BASE = "https://api.apidance.pro"
APIDANCE_API_KEY = os.getenv("APIDANCE_API_KEY", "")
MONTHS_LOOKBACK = 3
MAX_TWEETS_PER_KOL = 50

# Deep mode settings
DEEP_MAX_PAGES = 50          # 翻页上限（安全阀，~2000 条）
DEEP_MONTHS_LOOKBACK = 120   # 10 年，等于不限
DEEP_MAX_TWEETS = 9999       # 等于不限


# ---------------------------------------------------------------------------
# APIDance Client (extracted from crypto-historian/ai_inner_circle.py)
# ---------------------------------------------------------------------------

def apidance_get(endpoint, params=None, max_retries=3):
    """Generic GET with retry + rate limit handling."""
    url = f"{APIDANCE_BASE}{endpoint}"
    headers = {"apikey": APIDANCE_API_KEY}
    for attempt in range(max_retries):
        try:
            resp = requests.get(url, headers=headers, params=params, timeout=30)
            if resp.status_code == 429:
                wait = min(2 ** attempt * 5, 60)
                print(f"  Rate limited, waiting {wait}s...", file=sys.stderr)
                time.sleep(wait)
                continue
            resp.raise_for_status()
            return resp.json()
        except requests.exceptions.RequestException as e:
            if attempt < max_retries - 1:
                time.sleep(2 ** attempt)
                print(f"  Request failed (attempt {attempt+1}): {e}", file=sys.stderr)
            else:
                print(f"  Request failed after {max_retries} attempts: {e}", file=sys.stderr)
                return None
    return None


def get_user_profile(screen_name):
    """Fetch user profile via /graphql/UserByScreenName."""
    import json as _json
    variables = _json.dumps({"screen_name": screen_name})
    data = apidance_get("/graphql/UserByScreenName", {"variables": variables})
    if not data:
        return None
    user = data.get("data", {}).get("user", {}).get("result", {})
    if not user or user.get("__typename") == "UserUnavailable":
        return None
    core = user.get("core", {})
    legacy = user.get("legacy", {})
    return {
        "user_id": str(user.get("rest_id", "")),
        "screen_name": core.get("screen_name", screen_name),
        "name": core.get("name", ""),
        "description": legacy.get("description", ""),
        "followers_count": legacy.get("followers_count", legacy.get("normal_followers_count", 0)),
        "following_count": legacy.get("friends_count", 0),
        "tweet_count": legacy.get("statuses_count", 0),
        "profile_image_url": user.get("avatar", {}).get("image_url", ""),
        "location": legacy.get("location", ""),
        "verified": legacy.get("verified", False),
    }


# ---------------------------------------------------------------------------
# Tweet Parsing (handles APIDance's multiple response formats)
# ---------------------------------------------------------------------------

def _parse_tweet(raw):
    """Parse a tweet from APIDance /sapi response (flat format)."""
    if not raw:
        return None

    # New flat format: fields at top level
    if "tweet_id" in raw and "text" in raw:
        like_count = raw.get("favorite_count", 0) or 0
        retweet_count = raw.get("retweet_count", 0) or 0
        reply_count = raw.get("reply_count", 0) or 0
        quote_count = raw.get("quote_count", 0) or 0
        return {
            "tweet_id": str(raw["tweet_id"]),
            "text": raw.get("text", ""),
            "created_at": raw.get("created_at", ""),
            "like_count": like_count,
            "retweet_count": retweet_count,
            "reply_count": reply_count,
            "quote_count": quote_count,
            "view_count": raw.get("view_count", 0) or 0,
            "engagement": like_count + retweet_count + reply_count + quote_count,
            "is_retweet": raw.get("is_retweet", False),
        }

    # Legacy nested format (GraphQL / older API)
    result = raw.get("tweet_results", {}).get("result", raw) if "tweet_results" in raw else raw
    legacy = result.get("legacy", result)

    tweet_id = str(legacy.get("id_str", result.get("rest_id", "")))
    if not tweet_id:
        return None

    metrics = legacy.get("public_metrics", legacy)
    text = legacy.get("full_text", legacy.get("text", ""))

    like_count = metrics.get("favorite_count", metrics.get("like_count", 0)) or 0
    retweet_count = metrics.get("retweet_count", 0) or 0
    reply_count = metrics.get("reply_count", 0) or 0
    quote_count = metrics.get("quote_count", 0) or 0

    return {
        "tweet_id": tweet_id,
        "text": text,
        "created_at": legacy.get("created_at", ""),
        "like_count": like_count,
        "retweet_count": retweet_count,
        "reply_count": reply_count,
        "quote_count": quote_count,
        "view_count": 0,
        "engagement": like_count + retweet_count + reply_count + quote_count,
        "is_retweet": False,
    }


def _extract_tweets(data):
    """Extract tweet list from various APIDance response formats."""
    if not data:
        return [], None
    tweets_raw = []
    cursor = None

    if isinstance(data, dict):
        if "tweets" in data:
            tweets_raw = data["tweets"] if isinstance(data["tweets"], list) else []
            cursor = data.get("next_cursor") or data.get("cursor")
        elif "data" in data and isinstance(data["data"], dict):
            tweets_raw = data["data"].get("tweets", [])
            cursor = data["data"].get("next_cursor") or data["data"].get("cursor")
        elif "globalObjects" in data:
            tweets_obj = data["globalObjects"].get("tweets", {})
            tweets_raw = list(tweets_obj.values())

    parsed = [t for raw in tweets_raw if (t := _parse_tweet(raw))]
    return parsed, cursor


def get_user_tweets(user_id, screen_name, max_pages=3, months_lookback=MONTHS_LOOKBACK, max_tweets=MAX_TWEETS_PER_KOL):
    """Fetch user timeline via /sapi/UserTweets with pagination."""
    deep = max_pages > 3
    cutoff = datetime.now(timezone.utc) - timedelta(days=months_lookback * 30)
    all_tweets = []
    cursor = None

    for page in range(max_pages):
        params = {"user_id": user_id}
        if cursor:
            params["cursor"] = cursor
        data = apidance_get("/sapi/UserTweets", params)
        tweets, cursor = _extract_tweets(data)
        all_tweets.extend(tweets)
        if deep:
            print(f"  @{screen_name} page {page+1}: {len(tweets)} tweets (total: {len(all_tweets)})", file=sys.stderr)
        else:
            print(f"  @{screen_name} page {page+1}: {len(tweets)} tweets", file=sys.stderr)
        if not cursor or not tweets:
            break
        time.sleep(1)

    # Filter to recent tweets only, exclude retweets
    filtered = []
    earliest_date = None
    latest_date = None
    for t in all_tweets:
        if t.get("is_retweet"):
            continue
        try:
            created = datetime.strptime(t["created_at"], "%a %b %d %H:%M:%S %z %Y")
            if created >= cutoff:
                filtered.append(t)
                if deep:
                    if earliest_date is None or created < earliest_date:
                        earliest_date = created
                    if latest_date is None or created > latest_date:
                        latest_date = created
        except (ValueError, KeyError):
            filtered.append(t)  # keep if date unparseable

    if deep and earliest_date and latest_date:
        print(f"  @{screen_name} done: {len(filtered)} tweets spanning {earliest_date.strftime('%Y-%m')} to {latest_date.strftime('%Y-%m')}", file=sys.stderr)

    # Sort by engagement, keep top N
    filtered.sort(key=lambda t: t["engagement"], reverse=True)
    return filtered[:max_tweets]



# ---------------------------------------------------------------------------
# Orchestrator
# ---------------------------------------------------------------------------

def fetch_all(handles, mode="default"):
    """Fetch profile + tweets for all handles. Returns structured dict."""
    if mode == "deep":
        max_pages, months_lookback, max_tweets = DEEP_MAX_PAGES, DEEP_MONTHS_LOOKBACK, DEEP_MAX_TWEETS
    else:
        max_pages, months_lookback, max_tweets = 3, MONTHS_LOOKBACK, MAX_TWEETS_PER_KOL

    results = {}
    for handle in handles:
        handle = handle.strip().lstrip("@")
        if not handle:
            continue
        print(f"\n--- Fetching @{handle} ---", file=sys.stderr)

        profile = get_user_profile(handle)
        if not profile:
            print(f"  Could not resolve @{handle}, skipping.", file=sys.stderr)
            results[handle] = {"profile": None, "tweets": [], "error": f"Could not resolve @{handle}"}
            continue

        tweets = get_user_tweets(profile["user_id"], handle, max_pages=max_pages, months_lookback=months_lookback, max_tweets=max_tweets)
        if mode == "deep":
            print(f"  Got {len(tweets)} tweets (deep mode, all time)", file=sys.stderr)
        else:
            print(f"  Got {len(tweets)} tweets (top by engagement, last {MONTHS_LOOKBACK} months)", file=sys.stderr)

        results[handle] = {
            "profile": profile,
            "tweets": tweets,
            "error": None,
        }

    return results


def main():
    parser = argparse.ArgumentParser(description="Fetch KOL Twitter data via APIDance")
    parser.add_argument("--handles", required=True, help="Comma-separated Twitter handles")
    parser.add_argument("--output", required=True, help="Output JSON file path")
    parser.add_argument("--mode", choices=["default", "deep"], default="default",
                        help="Fetch mode (default: recent top 50, deep: full history)")
    args = parser.parse_args()

    handles = [h.strip() for h in args.handles.split(",")]

    if not APIDANCE_API_KEY:
        print("WARNING: APIDANCE_API_KEY not set. Outputting skeleton JSON.", file=sys.stderr)
        skeleton = {
            "fetched_at": datetime.now(timezone.utc).isoformat(),
            "api_available": False,
            "kols": {h.strip().lstrip("@"): {"profile": None, "tweets": [], "error": "No API key"} for h in handles},
        }
        with open(args.output, "w") as f:
            json.dump(skeleton, f, indent=2, ensure_ascii=False)
        print(f"Skeleton JSON written to {args.output}", file=sys.stderr)
        return

    kols = fetch_all(handles, mode=args.mode)

    output = {
        "fetched_at": datetime.now(timezone.utc).isoformat(),
        "api_available": True,
        "kols": kols,
    }

    with open(args.output, "w") as f:
        json.dump(output, f, indent=2, ensure_ascii=False)
    print(f"\nData written to {args.output}", file=sys.stderr)
    print(f"KOLs fetched: {len([k for k in kols.values() if not k.get('error')])}/{len(kols)}", file=sys.stderr)


if __name__ == "__main__":
    main()