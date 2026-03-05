#!/usr/bin/env python3
"""
GitBook.io Scraper — uses Playwright to handle JS-rendered GitBook sites.
Falls back to this when the static downloader fails (e.g., *.gitbook.io with Cloudflare).

Usage:
    python3 gitbook_playwright.py "https://example-labs.gitbook.io/example-docs/" -o output.md
"""
import argparse
import asyncio
import hashlib
import re
import sys
from urllib.parse import urljoin, urlparse

from markdownify import markdownify as md
from playwright.async_api import async_playwright


async def scrape_gitbook(base_url: str, output: str, section_only: bool = False):
    base_parsed = urlparse(base_url)
    base_domain = base_parsed.netloc
    base_path = base_parsed.path.rstrip("/")

    visited = set()
    pages = []  # (url, title, markdown)
    nav_links = []
    seen_hashes = set()

    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        context = await browser.new_context(
            user_agent="Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                       "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
        )
        page = await context.new_page()

        # 1. Load main page, extract nav links
        print(f"Loading {base_url}...", file=sys.stderr)
        await page.goto(base_url, wait_until="networkidle", timeout=30000)
        await asyncio.sleep(2)

        # Extract all navigation links from sidebar
        links = await page.eval_on_selector_all(
            "nav a[href], aside a[href], [class*='sidebar'] a[href], "
            "[class*='navigation'] a[href], [class*='menu'] a[href], "
            "[class*='toc'] a[href], [id*='toc'] a[href]",
            "els => els.map(e => ({href: e.href, text: e.textContent.trim()}))"
        )

        # Deduplicate and filter
        for link in links:
            href = link["href"].split("#")[0].rstrip("/")
            parsed = urlparse(href)
            if parsed.netloc != base_domain:
                continue
            if any(href.endswith(ext) for ext in [".pdf", ".png", ".jpg", ".svg"]):
                continue
            if section_only and not parsed.path.startswith(base_path):
                continue
            if href not in visited:
                visited.add(href)
                nav_links.append((href, link["text"]))

        # If no nav links found, try broader selector
        if not nav_links:
            links = await page.eval_on_selector_all(
                "a[href]",
                "els => els.map(e => ({href: e.href, text: e.textContent.trim()}))"
            )
            for link in links:
                href = link["href"].split("#")[0].rstrip("/")
                parsed = urlparse(href)
                if parsed.netloc != base_domain:
                    continue
                if section_only and not parsed.path.startswith(base_path):
                    continue
                if href not in visited:
                    visited.add(href)
                    nav_links.append((href, link["text"]))

        # Always include base URL
        base_clean = base_url.split("#")[0].rstrip("/")
        if base_clean not in visited:
            nav_links.insert(0, (base_clean, "Home"))
            visited.add(base_clean)

        print(f"Found {len(nav_links)} pages to scrape", file=sys.stderr)

        # 2. Scrape each page
        for i, (url, nav_title) in enumerate(nav_links):
            try:
                print(f"  [{i+1}/{len(nav_links)}] {url}", file=sys.stderr)
                await page.goto(url, wait_until="networkidle", timeout=20000)
                await asyncio.sleep(1)

                # Extract main content (try multiple selectors)
                content_html = None
                for selector in [
                    "main", "[class*='page-body']", "[class*='content']",
                    "[role='main']", "article", ".markdown-body",
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
                    # Fallback: get body minus nav/sidebar
                    content_html = await page.eval_on_selector(
                        "body",
                        """el => {
                            const clone = el.cloneNode(true);
                            clone.querySelectorAll('nav, aside, header, footer, [class*="sidebar"], [class*="navigation"]')
                                .forEach(e => e.remove());
                            return clone.innerHTML;
                        }"""
                    )

                # Convert to markdown
                page_md = md(content_html, heading_style="ATX", strip=["script", "style", "img"])
                page_md = re.sub(r'\n{3,}', '\n\n', page_md).strip()

                # Deduplicate by content hash
                content_hash = hashlib.md5(page_md[:500].encode()).hexdigest()
                if content_hash in seen_hashes:
                    continue
                seen_hashes.add(content_hash)

                # Get page title
                title = await page.title()
                title = title.split("|")[0].split("–")[0].strip() if title else nav_title

                if len(page_md) > 50:
                    pages.append((url, title, page_md))

            except Exception as e:
                print(f"  ⚠ Failed: {e}", file=sys.stderr)
                continue

        await browser.close()

    # 3. Assemble output
    print(f"\nAssembling {len(pages)} pages...", file=sys.stderr)

    toc = "# Table of Contents\n\n"
    body = ""
    for i, (url, title, content) in enumerate(pages):
        slug = re.sub(r'[^a-z0-9]+', '-', title.lower()).strip('-')
        toc += f"- [{title}](#{slug})\n"
        body += f"\n\n---\n\n## {title}\n\n*Source: {url}*\n\n{content}\n"

    full_md = toc + body

    with open(output, "w", encoding="utf-8") as f:
        f.write(full_md)

    print(f"\n✅ Saved {len(pages)} pages → {output}", file=sys.stderr)
    return len(pages)


def main():
    parser = argparse.ArgumentParser(description="GitBook.io Playwright Scraper")
    parser.add_argument("url", help="GitBook URL to scrape")
    parser.add_argument("-o", "--output", required=True, help="Output markdown file")
    parser.add_argument("-s", "--section-only", action="store_true",
                        help="Only scrape pages within the same URL section")
    args = parser.parse_args()
    asyncio.run(scrape_gitbook(args.url, args.output, args.section_only))


if __name__ == "__main__":
    main()
