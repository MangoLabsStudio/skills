#!/usr/bin/env python3
"""
Project Research Scraper — auto-discover and batch download all public info for a project.

Modes:
  --discover {url}    Crawl entry points, discover all external links, classify, output JSON
  --config {file}     Batch scrape from a JSON source list
  --urls {csv}        Batch scrape from comma-separated URLs

Usage:
    # Auto-discover from project website
    python3 project_scraper.py --discover "https://www.example-project.com" -o ./research/

    # Batch scrape from config
    python3 project_scraper.py --config sources.json -o ./research/
"""
import argparse
import asyncio
import hashlib
import json
import os
import re
import subprocess
import sys
from pathlib import Path
from urllib.parse import urlparse

from markdownify import markdownify as md
from playwright.async_api import async_playwright


# ---------------------------------------------------------------------------
# Link classification rules for crypto projects
# ---------------------------------------------------------------------------

# Domains we always skip (social, auth, tracking, etc.)
SKIP_DOMAINS = {
    "twitter.com", "x.com", "t.me", "telegram.org",
    "discord.com", "discord.gg",
    "facebook.com", "instagram.com", "linkedin.com", "reddit.com",
    "google.com", "googleapis.com", "gstatic.com",
    "apple.com", "apps.apple.com", "play.google.com",
    "cloudflare.com", "cdn.jsdelivr.net",
    "fonts.googleapis.com", "analytics.google.com",
    "mailto:", "javascript:",
}

# Internal paths that are app/functional, not content — skip these
SKIP_INTERNAL_PATHS = {
    "login", "signup", "register", "auth", "oauth", "callback",
    "dashboard", "settings", "profile", "account", "wallet",
    "trade", "swap", "pool", "stake", "bridge", "farm", "vault", "earn",
    "app", "dapp", "connect", "launch",
    "api", "graphql", "webhook", "ws",
    "admin", "manage", "console",
    "cart", "checkout", "payment",
    "search", "404", "500", "error",
    "static", "assets", "images", "fonts", "css", "js",
    "sitemap", "robots", "manifest",
}

# Subdomains that are app/infra, not content
SKIP_SUBDOMAINS = {
    "app", "production", "staging", "dev", "beta", "test",
    "api", "cdn", "static", "admin", "console", "ws",
}
CLASSIFY_RULES = [
    # (pattern, type, name_prefix)
    (lambda u, d: "gitbook.io" in d, "docs", "docs"),  # All GitBook sites are docs
    (lambda u, d: "/docs" in u and d not in SKIP_DOMAINS, "docs", "docs"),
    (lambda u, d: "medium.com" in d, "blog", "medium"),
    (lambda u, d: "mirror.xyz" in d, "blog", "mirror"),
    (lambda u, d: "/blog" in u, "blog", "blog"),
    (lambda u, d: "/insights" in u, "blog", "insights"),
    (lambda u, d: "github.com" in d, "github", "github"),
    (lambda u, d: "dune.com" in d, "dune", "dune-stats"),
    (lambda u, d: "defillama.com" in d, "page", "defillama"),
    (lambda u, d: "blockworks.co" in d, "page", "blockworks"),
    (lambda u, d: "theblock.co" in d, "page", "theblock"),
    (lambda u, d: "coindesk.com" in d, "page", "coindesk"),
    (lambda u, d: "cointelegraph.com" in d, "page", "cointelegraph"),
    (lambda u, d: "decrypt.co" in d, "page", "decrypt"),
    (lambda u, d: "drive.google.com" in d, "skip", ""),
    (lambda u, d: "jobs." in d or "ashby" in d, "skip", ""),
    (lambda u, d: "youtube.com" in d or "youtu.be" in d, "skip", ""),
]


async def scrape_single_page(page, url: str) -> str | None:
    """Scrape a single page, return markdown content."""
    try:
        await page.goto(url, wait_until="networkidle", timeout=25000)
        await asyncio.sleep(1.5)

        content_html = None
        for selector in [
            "article", "main", "[class*='post-content']", "[class*='article']",
            "[class*='page-body']", "[class*='content']", "[role='main']",
            ".markdown-body", "[class*='blog']",
        ]:
            try:
                el = await page.query_selector(selector)
                if el:
                    content_html = await el.inner_html()
                    if len(content_html.strip()) > 100:
                        break
            except Exception:
                continue

        if not content_html or len(content_html.strip()) < 50:
            content_html = await page.eval_on_selector(
                "body",
                """el => {
                    const clone = el.cloneNode(true);
                    clone.querySelectorAll('nav, aside, header, footer, [class*="sidebar"], [class*="navigation"], script, style')
                        .forEach(e => e.remove());
                    return clone.innerHTML;
                }"""
            )

        page_md = md(content_html, heading_style="ATX", strip=["script", "style"])
        page_md = re.sub(r'\n{3,}', '\n\n', page_md).strip()
        return page_md if len(page_md) > 50 else None
    except Exception as e:
        print(f"  ⚠ Failed {url}: {e}", file=sys.stderr)
        return None


def classify_url(url: str, project_domain: str = "") -> tuple[str, str]:
    """Classify a URL into (type, name_prefix). Returns ('skip', '') for irrelevant links."""
    parsed = urlparse(url)
    domain = parsed.netloc.lower()
    path = parsed.path.lower()

    for skip in SKIP_DOMAINS:
        if skip in domain or url.startswith(skip):
            return "skip", ""

    # Skip app/infra subdomains (app.xxx.com, production.xxx.com, etc.)
    subdomain = domain.split(".")[0] if domain.count(".") >= 2 else ""
    if subdomain in SKIP_SUBDOMAINS:
        return "skip", ""

    # Skip individual blog posts (only keep blog index pages)
    # A blog index is /blog or /blog/ — a post is /blog/some-slug
    blog_path_parts = [p for p in path.split("/") if p]
    if "blog" in blog_path_parts:
        blog_idx = blog_path_parts.index("blog")
        if blog_idx < len(blog_path_parts) - 1:
            # This is a specific post, not the index
            return "skip", ""

    # Skip links that clearly belong to other projects (not ours)
    if project_domain:
        proj = project_domain.lower()
        # Allow: same project domain, known platforms (medium, github, dune, etc.)
        known_platforms = {"medium.com", "mirror.xyz", "github.com", "dune.com",
                          "defillama.com", "blockworks.co", "theblock.co", "coindesk.com",
                          "cointelegraph.com", "decrypt.co", "gitbook.io"}
        is_project_related = (proj in domain or
                              any(p in domain for p in known_platforms) or
                              proj in url.lower())
        if not is_project_related:
            return "skip", ""

    for rule_fn, src_type, prefix in CLASSIFY_RULES:
        if rule_fn(url, domain):
            return src_type, prefix

    # Internal content sections (added by auto-discovery) default to "page"
    if project_domain and proj in domain:
        section = [p for p in path.split("/") if p]
        if not section:
            return "page", "homepage"  # Root page of project domain
        if section[0] not in SKIP_INTERNAL_PATHS:
            return "page", section[0]

    return "skip", ""


async def discover_links(entry_urls: list[str], project_domain: str = "") -> dict:
    """Crawl entry points, discover all external links, classify them.
    Returns {"sources": [...], "social_links": [...]}."""

    all_links = {}  # href -> {text, domain, from}
    social_links = set()  # Twitter/X handles discovered from the page

    # Infer project domain if not given
    if not project_domain and entry_urls:
        d = urlparse(entry_urls[0]).netloc.replace("www.", "")
        project_domain = d.split(".")[0]  # e.g., "example" from "example.com"

    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        page = await browser.new_page(
            user_agent="Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                       "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
        )

        for entry in entry_urls:
            print(f"\n🔍 Discovering links from {entry}...", file=sys.stderr)
            try:
                await page.goto(entry, wait_until="networkidle", timeout=30000)
                await asyncio.sleep(2)
                # Scroll to reveal footer
                for _ in range(5):
                    await page.evaluate("window.scrollTo(0, document.body.scrollHeight)")
                    await asyncio.sleep(0.5)

                links = await page.eval_on_selector_all(
                    "a[href]",
                    "els => els.map(e => ({href: e.href, text: e.textContent.trim().substring(0, 100)}))"
                )
                for l in links:
                    href = l["href"].split("#")[0].split("?")[0].rstrip("/")
                    if href and href.startswith("http") and href not in all_links:
                        all_links[href] = {"text": l["text"], "domain": urlparse(href).netloc}

                # Also extract URLs from page text (catches GitHub/Dune links in content)
                text_urls = await page.evaluate("""() => {
                    const text = document.body.innerText;
                    const matches = text.match(/https?:\\/\\/[^\\s<>"'\\)\\]]+/g) || [];
                    return [...new Set(matches)];
                }""")
                for href in text_urls:
                    href = href.split("#")[0].split("?")[0].rstrip("/")
                    if href not in all_links and href.startswith("http"):
                        all_links[href] = {"text": "", "domain": urlparse(href).netloc}

            except Exception as e:
                print(f"  ⚠ Failed: {e}", file=sys.stderr)

        await browser.close()

    # Add entry URLs themselves as high-priority sources
    entry_links = {}
    for entry in entry_urls:
        entry_clean = entry.split("#")[0].split("?")[0].rstrip("/")
        entry_domain = urlparse(entry_clean).netloc
        entry_links[entry_clean] = {"text": "", "domain": entry_domain, "is_entry": True}

    # Auto-discover internal content sections from the main domain
    # Instead of hardcoding /blog, /docs, etc., collect all unique first-level
    # internal paths and keep those that aren't app/functional pages
    if entry_urls:
        main_netloc = urlparse(entry_urls[0]).netloc.replace("www.", "")
        main_origin = urlparse(entry_urls[0]).scheme + "://" + urlparse(entry_urls[0]).netloc
        seen_sections = set()
        for href, info in all_links.items():
            link_netloc = info["domain"].replace("www.", "")
            if link_netloc != main_netloc:
                continue
            path_parts = [p for p in urlparse(href).path.strip("/").split("/") if p]
            if not path_parts:
                continue
            section = path_parts[0].lower()
            if section in seen_sections or section in SKIP_INTERNAL_PATHS:
                continue
            # Skip paths that look like IDs/hashes (hex strings, UUIDs)
            if len(section) > 20 or re.match(r'^[0-9a-f-]{8,}$', section):
                continue
            seen_sections.add(section)
            # Add the section root as a candidate source
            candidate = f"{main_origin}/{path_parts[0]}"
            if candidate not in entry_links and candidate not in all_links:
                entry_links[candidate] = {"text": "", "domain": urlparse(candidate).netloc, "is_entry": True}

    # Classify and deduplicate — process entry URLs first so they take priority
    sources = []
    seen_prefixes = {}  # prefix -> count, for dedup naming
    seen_domains_types = set()  # (domain_base, type) to merge blog posts into one entry

    # Entry URLs first, then discovered links
    ordered_links = list(entry_links.items()) + sorted(
        ((k, v) for k, v in all_links.items() if k not in entry_links), key=lambda x: x[0]
    )

    for href, info in ordered_links:
        # Capture twitter/x.com handles as social metadata
        parsed_href = urlparse(href)
        href_domain = parsed_href.netloc.lower()
        if "twitter.com" in href_domain or "x.com" in href_domain:
            # Extract handle from path like /username or /username/status/...
            path_parts = [p for p in parsed_href.path.strip("/").split("/") if p]
            if path_parts and not path_parts[0].startswith(("search", "hashtag", "i", "intent", "share", "home", "explore", "settings", "notifications")):
                social_links.add(path_parts[0].lstrip("@").lower())
            continue  # Still skip from sources, but we captured the handle

        src_type, prefix = classify_url(href, project_domain)
        if src_type == "skip":
            continue

        # Deduplicate: one entry per (domain, type, path_root) for blogs/docs
        # This keeps /blog and /insights as separate sources on the same domain
        domain_base = info["domain"].replace("www.", "")
        path_root = urlparse(href).path.strip("/").split("/")[0] if urlparse(href).path.strip("/") else ""
        dedup_key = (domain_base, src_type, path_root)
        if dedup_key in seen_domains_types and src_type in ("blog", "docs", "page"):
            continue
        seen_domains_types.add(dedup_key)

        # Generate unique name
        if prefix in seen_prefixes:
            seen_prefixes[prefix] += 1
            name = f"{project_domain}-{prefix}-{seen_prefixes[prefix]}"
        else:
            seen_prefixes[prefix] = 1
            name = f"{project_domain}-{prefix}"

        sources.append({
            "url": href,
            "type": src_type,
            "name": name,
            "link_text": info["text"][:80],
        })

    return {"sources": sources, "social_links": sorted(social_links)}


def scrape_github_repo(repo_url: str, output_path: Path, name: str) -> dict | None:
    """Download a GitHub repo's key files as a single markdown doc."""
    parsed = urlparse(repo_url)
    parts = parsed.path.strip("/").split("/")
    if len(parts) < 2:
        return None
    owner, repo = parts[0], parts[1]
    full_repo = f"{owner}/{repo}"

    print(f"  Fetching GitHub repo {full_repo}...", file=sys.stderr)
    out_file = output_path / f"{name}.md"

    sections = []
    sections.append(f"# {full_repo}\n\n*Source: {repo_url}*\n")

    # README
    try:
        result = subprocess.run(
            ["gh", "api", f"repos/{full_repo}/readme", "--jq", ".content"],
            capture_output=True, text=True, timeout=15
        )
        if result.returncode == 0 and result.stdout.strip():
            import base64
            readme = base64.b64decode(result.stdout.strip()).decode("utf-8", errors="replace")
            sections.append(f"## README\n\n{readme}\n")
    except Exception:
        pass

    # Get file tree
    try:
        result = subprocess.run(
            ["gh", "api", f"repos/{full_repo}/git/trees/main?recursive=1",
             "--jq", '.tree[] | select(.type=="blob") | .path'],
            capture_output=True, text=True, timeout=15
        )
        if result.returncode == 0:
            files = [f for f in result.stdout.strip().split("\n") if f]

            # Fetch key files: examples, configs, changelogs, core source
            import base64
            priority_patterns = [
                "CHANGELOG", "examples/", "src/", "lib/",
                "pyproject.toml", "package.json", "Cargo.toml",
            ]
            fetched = 0
            for fpath in files:
                if fetched >= 30:
                    break
                if any(p in fpath for p in priority_patterns) and not fpath.endswith((".pyc", ".lock")):
                    if "__pycache__" in fpath or "node_modules" in fpath:
                        continue
                    try:
                        r = subprocess.run(
                            ["gh", "api", f"repos/{full_repo}/contents/{fpath}", "--jq", ".content"],
                            capture_output=True, text=True, timeout=10
                        )
                        if r.returncode == 0 and r.stdout.strip():
                            content = base64.b64decode(r.stdout.strip()).decode("utf-8", errors="replace")
                            ext = fpath.rsplit(".", 1)[-1] if "." in fpath else ""
                            sections.append(f"## {fpath}\n\n```{ext}\n{content}\n```\n")
                            fetched += 1
                    except Exception:
                        pass
    except Exception:
        pass

    if len(sections) > 1:
        out_file.write_text("\n---\n\n".join(sections), encoding="utf-8")
        size_kb = out_file.stat().st_size / 1024
        print(f"  ✅ {len(sections)-1} files → {out_file} ({size_kb:.0f}KB)", file=sys.stderr)
        return {"name": name, "pages": len(sections)-1, "file": str(out_file), "size_kb": round(size_kb)}
    return None


async def scrape_gitbook_site(page, base_url: str) -> list[tuple[str, str, str]]:
    """Scrape a full GitBook/doc site. Returns [(url, title, markdown), ...]"""
    base_domain = urlparse(base_url).netloc
    visited = set()
    pages = []
    seen_hashes = set()

    print(f"  Loading {base_url}...", file=sys.stderr)
    await page.goto(base_url, wait_until="networkidle", timeout=30000)
    await asyncio.sleep(2)

    links = await page.eval_on_selector_all(
        "nav a[href], aside a[href], [class*='sidebar'] a[href], "
        "[class*='navigation'] a[href], [class*='menu'] a[href], "
        "[class*='toc'] a[href], [id*='toc'] a[href]",
        "els => els.map(e => ({href: e.href, text: e.textContent.trim()}))"
    )

    nav_links = []
    for link in links:
        href = link["href"].split("#")[0].rstrip("/")
        parsed = urlparse(href)
        if parsed.netloc != base_domain:
            continue
        if any(href.endswith(ext) for ext in [".pdf", ".png", ".jpg", ".svg"]):
            continue
        if href not in visited:
            visited.add(href)
            nav_links.append((href, link["text"]))

    base_clean = base_url.split("#")[0].rstrip("/")
    if base_clean not in visited:
        nav_links.insert(0, (base_clean, "Home"))

    print(f"  Found {len(nav_links)} pages", file=sys.stderr)

    for i, (url, nav_title) in enumerate(nav_links):
        print(f"    [{i+1}/{len(nav_links)}] {url}", file=sys.stderr)
        content = await scrape_single_page(page, url)
        if content:
            content_hash = hashlib.md5(content[:500].encode()).hexdigest()
            if content_hash not in seen_hashes:
                seen_hashes.add(content_hash)
                title = await page.title()
                title = title.split("|")[0].split("–")[0].strip() if title else nav_title
                pages.append((url, title, content))

    return pages


async def scrape_blog(page, blog_url: str, max_scroll: int = 15) -> list[tuple[str, str, str]]:
    """Scrape a blog index page — discover posts, then scrape each."""
    base_domain = urlparse(blog_url).netloc
    print(f"  Loading blog {blog_url}...", file=sys.stderr)
    await page.goto(blog_url, wait_until="networkidle", timeout=30000)

    # Scroll to load all posts
    for _ in range(max_scroll):
        await page.evaluate("window.scrollTo(0, document.body.scrollHeight)")
        await asyncio.sleep(0.8)

    links = await page.eval_on_selector_all("a[href]", "els => els.map(e => e.href)")
    blog_path = urlparse(blog_url).path.rstrip("/")
    post_urls = sorted(set(
        l.split("#")[0].rstrip("/") for l in links
        if blog_path + "/" in l and urlparse(l).netloc.replace("www.", "") == base_domain.replace("www.", "")
        and "twitter" not in l and "mailto" not in l
    ))

    print(f"  Found {len(post_urls)} blog posts", file=sys.stderr)
    pages = []
    for i, url in enumerate(post_urls):
        print(f"    [{i+1}/{len(post_urls)}] {url}", file=sys.stderr)
        content = await scrape_single_page(page, url)
        if content:
            title = await page.title()
            title = title.split("|")[0].split("–")[0].strip() if title else url.split("/")[-1]
            pages.append((url, title, content))

    return pages


def assemble_markdown(pages: list[tuple[str, str, str]], title: str) -> str:
    """Assemble pages into a single markdown file with TOC."""
    toc = f"# {title}\n\n## Table of Contents\n\n"
    body = ""
    for url, page_title, content in pages:
        slug = re.sub(r'[^a-z0-9]+', '-', page_title.lower()).strip('-')
        toc += f"- [{page_title}](#{slug})\n"
        body += f"\n\n---\n\n## {page_title}\n\n*Source: {url}*\n\n{content}\n"
    return toc + body


async def run(sources: list[dict], output_dir: str):
    """Main scraper orchestrator."""
    output_path = Path(output_dir)
    output_path.mkdir(parents=True, exist_ok=True)

    # Separate GitHub sources (handled outside Playwright)
    github_sources = [s for s in sources if s.get("type") == "github"]
    web_sources = [s for s in sources if s.get("type") not in ("github", "skip", "dune")]
    dune_sources = [s for s in sources if s.get("type") == "dune"]

    results = []

    # Handle GitHub repos via gh CLI
    for src in github_sources:
        name = src.get("name", "github-repo")
        r = scrape_github_repo(src["url"], output_path, name)
        if r:
            results.append(r)

    # Handle Dune dashboards (just save reference)
    for src in dune_sources:
        name = src.get("name", "dune-stats")
        out_file = output_path / f"{name}.md"
        out_file.write_text(
            f"# Dune Dashboard\n\n*URL: {src['url']}*\n\n"
            "Dune dashboards render charts via canvas and require manual inspection.\n"
            f"Open in browser: [{src['url']}]({src['url']})\n",
            encoding="utf-8"
        )
        results.append({"name": name, "pages": 1, "file": str(out_file), "size_kb": 0})

    # Handle web sources via Playwright
    if web_sources:
        async with async_playwright() as p:
            browser = await p.chromium.launch(headless=True)
            context = await browser.new_context(
                user_agent="Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                           "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
            )
            page = await context.new_page()

            for src in web_sources:
                url = src["url"]
                name = src.get("name", urlparse(url).netloc.replace(".", "-"))
                src_type = src.get("type", "auto")

                # Auto-detect type
                if src_type == "auto":
                    src_type, _ = classify_url(url)

                print(f"\n{'='*60}", file=sys.stderr)
                print(f"[{src_type.upper()}] {name}: {url}", file=sys.stderr)
                print(f"{'='*60}", file=sys.stderr)

                if src_type == "skip":
                    print(f"  Skipping", file=sys.stderr)
                    continue

                try:
                    if src_type == "docs":
                        pages = await scrape_gitbook_site(page, url)
                    elif src_type == "blog":
                        pages = await scrape_blog(page, url)
                        # Fallback: if blog scraper finds no posts, scrape as single page
                        if not pages:
                            print(f"  ↳ No posts found, scraping as single page...", file=sys.stderr)
                            content = await scrape_single_page(page, url)
                            if content:
                                title = await page.title()
                                pages = [(url, title or name, content)]
                    elif src_type == "page":
                        content = await scrape_single_page(page, url)
                        if content:
                            title = await page.title()
                            pages = [(url, title or name, content)]
                        else:
                            pages = []
                    else:
                        pages = []

                    if pages:
                        out_file = output_path / f"{name}.md"
                        full_md = assemble_markdown(pages, name)
                        out_file.write_text(full_md, encoding="utf-8")
                        size_kb = out_file.stat().st_size / 1024
                        print(f"  ✅ {len(pages)} pages → {out_file} ({size_kb:.0f}KB)", file=sys.stderr)
                        results.append({"name": name, "pages": len(pages), "file": str(out_file), "size_kb": round(size_kb)})
                    else:
                        print(f"  ⚠ No content extracted", file=sys.stderr)

                except Exception as e:
                    print(f"  ❌ Error: {e}", file=sys.stderr)

            await browser.close()

    # Summary
    print(f"\n{'='*60}", file=sys.stderr)
    print(f"DONE — {len(results)} sources scraped:", file=sys.stderr)
    for r in results:
        print(f"  {r['name']}: {r['pages']} pages, {r['size_kb']}KB → {r['file']}", file=sys.stderr)

    # Write manifest
    manifest_path = output_path / "_sources.json"
    manifest_path.write_text(json.dumps(results, indent=2, ensure_ascii=False), encoding="utf-8")
    print(f"\nManifest → {manifest_path}", file=sys.stderr)

    return results


def main():
    parser = argparse.ArgumentParser(description="Project Research Scraper")
    parser.add_argument("--discover", help="Entry URL(s) to discover links from (comma-separated)")
    parser.add_argument("--config", help="JSON config file with sources list")
    parser.add_argument("--urls", help="Comma-separated URLs (auto-detect type)")
    parser.add_argument("--output-dir", "-o", required=True, help="Output directory")
    parser.add_argument("--discover-only", action="store_true",
                        help="Only discover links, don't scrape (outputs JSON)")
    args = parser.parse_args()

    if args.discover:
        entry_urls = [u.strip() for u in args.discover.split(",")]
        result = asyncio.run(discover_links(entry_urls))
        sources = result["sources"]
        social_links = result["social_links"]

        # Print discovered sources
        print(f"\n📋 Discovered {len(sources)} sources:", file=sys.stderr)
        for s in sources:
            label = f" ({s['link_text']})" if s.get("link_text") else ""
            print(f"  [{s['type']:6s}] {s['name']}: {s['url']}{label}", file=sys.stderr)
        if social_links:
            print(f"\n🐦 Social handles found: {', '.join(f'@{h}' for h in social_links)}", file=sys.stderr)

        if args.discover_only:
            # Output JSON to stdout for piping
            output = {"sources": sources, "social_links": social_links}
            print(json.dumps(output, indent=2, ensure_ascii=False))
            return

        # Filter out skips and scrape
        sources = [s for s in sources if s["type"] != "skip"]
        asyncio.run(run(sources, args.output_dir))

    elif args.config:
        with open(args.config) as f:
            sources = json.load(f)
        asyncio.run(run(sources, args.output_dir))

    elif args.urls:
        sources = [{"url": u.strip()} for u in args.urls.split(",")]
        asyncio.run(run(sources, args.output_dir))

    else:
        print("ERROR: Provide --discover, --config, or --urls", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
