---
name: research-project
description: >
  Auto-discover and download all public information about a crypto/web3 project.
  Crawls entry URLs, discovers external links (docs, blog, medium, github, media coverage),
  captures social handles, fetches Twitter data, and batch-downloads everything to the
  project's research directory.
  Triggers: "/research-project", "research project", "抓项目资料", "collect project info"
disable-model-invocation: true
---

# Research Project

Auto-discover and batch-download all public information about a project, including Twitter/X presence.

## Setup

1. Run `setup.sh` from the skill root to create a local venv and install dependencies (including Playwright Chromium).
2. For Twitter data fetching, also install the `kol-shortlist` sibling skill and set `APIDANCE_API_KEY`.

## Variables

- `{skill_path}` — absolute path to this skill directory (resolve at runtime)
- `{kol_skill_path}` — absolute path to the `kol-shortlist` sibling skill (typically `{skill_path}/../kol-shortlist`)
- `{project}` — project name provided by the user
- `{output_dir}` — output directory; defaults to `./{project}-research/`, or `Projects/ClientWork/{project}/research/` if it exists

## Step 1: Input

1. Use `$ARGUMENTS` as the project name. If empty, ask the user.
2. Check if a project directory exists at `Projects/ClientWork/{project}/`.
3. Determine entry URLs:
   - If `_project.md` exists, scan it for URLs (website, docs, social links)
   - Extract any known Twitter handles from `_project.md` (look for twitter.com/x.com links or `@handle` mentions)
   - Ask the user for the project's main website URL if not found
   - Common entry points to try: `https://www.{project}.com`, `https://www.{project}.io`, `https://docs.{project}.com`

## Step 2: Discover Links

Run the discovery phase to find all external links and social handles:

```bash
"{skill_path}/scripts/venv/bin/python3" \
  "{skill_path}/scripts/project_scraper.py" \
  --discover "{entry_urls_comma_separated}" \
  --discover-only \
  -o "/tmp/" 2>/dev/null
```

This outputs JSON with two fields:
- `sources`: list of web sources with types `docs`, `blog`, `github`, `page`, `dune`
- `social_links`: list of Twitter/X handles discovered from the website

Merge any handles from Step 1 (`_project.md`) with the auto-discovered `social_links`.

## Step 3: Review & Confirm

Show the user the discovered sources AND social handles:

```
📋 Discovered sources for {project}:
 Type    Name              URL
 docs    project-docs      https://docs.example.io/docs
 blog    project-medium    https://medium.com/@example
 github  project-github    https://github.com/org/repo
 page    project-coverage  https://blockworks.co/news/...

🐦 Twitter handles found: @example_official, @example_labs
```

Ask the user: "Scrape all of these, or remove any? Any Twitter handles to add/remove?" Let them confirm or filter.

## Step 4: Web Scrape

Save the confirmed web sources to a temp config, then run:

```bash
"{skill_path}/scripts/venv/bin/python3" \
  "{skill_path}/scripts/project_scraper.py" \
  --config /tmp/{project}_sources.json \
  -o "{output_dir}"
```

For `*.gitbook.io` docs that fail with the batch scraper, fall back to the Playwright GitBook scraper:

```bash
"{skill_path}/scripts/venv/bin/python3" \
  "{skill_path}/scripts/gitbook_playwright.py" \
  "{gitbook_url}" \
  -o "{output_dir}/{project}-docs.md"
```

## Step 5: Twitter Fetch

If there are confirmed Twitter handles, fetch their data via APIDance (requires `kol-shortlist` sibling skill):

```bash
APIDANCE_API_KEY="${APIDANCE_API_KEY}" \
  "{kol_skill_path}/scripts/venv/bin/python3" \
  "{kol_skill_path}/scripts/fetch_kol_data.py" \
  --handles "{handles_comma_separated}" \
  --output /tmp/{project}_twitter.json
```

**Note:** Step 4 and Step 5 can run in parallel.

If no Twitter handles were found or confirmed, skip Steps 5-6 entirely.

## Step 6: Twitter Analysis

Read `/tmp/{project}_twitter.json` and generate a markdown analysis file at:
`{output_dir}/{project}-twitter.md`

Use this template:

```markdown
# {Project} — Twitter/X Presence

*Generated: {date} | Handles: {handles}*

## Profile Overview

| Field | Value |
|-------|-------|
| Handle | @{handle} |
| Display Name | {name} |
| Bio | {bio} |
| Followers | {followers} |
| Following | {following} |
| Account Created | {created_at} |
| Verified | {verified} |

(Repeat table for each handle if multiple)

## Engagement Statistics

- **Average Likes**: {avg_likes}
- **Average Retweets**: {avg_retweets}
- **Average Replies**: {avg_replies}
- **Posting Frequency**: ~{posts_per_week} posts/week (estimated from recent tweets)

## Content Themes

Analyze the recent tweets and identify 3-5 recurring themes:
1. {theme_1} — {brief description}
2. {theme_2} — {brief description}
...

## Top Tweets (by engagement)

| Date | Tweet | Likes | RTs | Replies |
|------|-------|-------|-----|---------|
| {date} | {text_truncated_80chars} | {likes} | {rts} | {replies} |
(Top 10 tweets)

## Key Observations

- {observation_1}
- {observation_2}
- {observation_3}
```

## Step 7: Summary

After all scraping is complete, report everything:

```
✅ Project research complete — {project}
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
 File                        Size    Pages   Source
 {project}-docs.md           157KB   27      GitBook
 {project}-sdk.md            148KB   15      GitHub
 {project}-medium.md         91KB    12      Medium
 {project}-blog.md           11KB    6       Blog
 {project}-twitter.md        8KB     —       Twitter/X
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
Total: {n} files, {total_size}
```

## Supported Source Types

| Type | How it's scraped | Examples |
|------|-----------------|----------|
| `docs` | Full site crawl via nav links | GitBook, Mintlify, Docusaurus |
| `blog` | Scroll to discover posts, scrape each | Medium, Mirror, /blog pages |
| `github` | gh CLI to download README + source files | SDK repos, protocol repos |
| `dune` | Save reference (charts are canvas-rendered) | Dune dashboards |
| `page` | Single page scrape | Media articles, landing pages |
| `twitter` | APIDance API → Claude analysis | Project official accounts |

## Error Handling

- `*.gitbook.io` sites may need the Playwright fallback engine
- Sites behind Cloudflare/paywall may timeout — note them and move on
- GitHub repos require `gh` CLI to be authenticated
- Large blogs (100+ posts) may take several minutes
- Twitter fetch may fail if handles are invalid — skip and note in summary
- If no Twitter handles found, Steps 5-6 are skipped automatically

## Examples

```
/research-project ExampleDAO
/research-project SomeProtocol
```
