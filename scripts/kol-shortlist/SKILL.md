---
name: kol-shortlist
description: >
  Generate a Twitter-enriched KOL shortlist CSV. Fetches real Twitter data
  (profiles + recent tweets) via APIDance API, then generates intelligent
  Profile and Campaign Fit descriptions based on actual content.
  Triggers: "generate KOL shortlist", "create KOL list", "build KOL CSV",
  "KOL shortlist for", "/kol-shortlist"
disable-model-invocation: true
---

# KOL Shortlist Generator

Generate a KOL shortlist CSV enriched with real Twitter data and AI-written descriptions.

## Setup

1. Run `setup.sh` from the skill root to create a local venv and install dependencies.
2. Set the `APIDANCE_API_KEY` environment variable (e.g., in your shell profile or `.env`).

## Variables

- `{skill_path}` — absolute path to this skill directory (resolve at runtime via the location of this file)
- `{project}` — project name provided by the user
- `{project_dir}` — project directory; defaults to `Projects/ClientWork/{project}/` relative to the workspace root, but the user may specify any path

## Step 1: Input Collection

1. Use `$ARGUMENTS` as the project name. If empty, ask the user which project.
2. Try to locate a project directory at `Projects/ClientWork/{project}/`.
   - If not found, ask the user for the project directory path (or a campaign brief directly).
3. If a `_project.md` exists in the project directory, read it for campaign context.
   - If missing, ask the user to provide a 2-3 sentence campaign brief.
4. Ask the user for:
   - **Twitter handles** (comma-separated, e.g., "alice_web3, bob_defi, carol_nft")
   - **Campaign requirements** (optional — what kind of KOLs are they looking for?)

Store the campaign context for Step 3.

## Step 2: Fetch Twitter Data

Run the data fetcher script:

```bash
APIDANCE_API_KEY="${APIDANCE_API_KEY}" \
  "{skill_path}/scripts/venv/bin/python3" \
  "{skill_path}/scripts/fetch_kol_data.py" \
  --handles "{comma_separated_handles}" \
  --output /tmp/kol_data.json
```

After execution:
- Read `/tmp/kol_data.json`
- Check `api_available` field
- If `false`: warn user that descriptions will be handle-name-only, mark with `[NO API DATA]`
- If any individual KOL has `error`: note it, continue with the rest
- Report: "Fetched data for X/Y KOLs successfully"

## Step 3: Per-KOL Analysis

For each KOL in the JSON where `error` is null, read their profile and tweets.

### Analysis Prompt Template

Use the following prompt for each KOL. Replace variables with actual data:

```
Analyze this KOL for a campaign shortlist.

@{handle} ({name})
Bio: "{description}"
Followers: {followers_count}

Their top 20 tweets by engagement (last 3 months):
{top_tweets}

Campaign context:
{campaign_brief}

Generate exactly two fields:

1. Profile (1-2 sentences): Identify their PRIMARY content identity from tweet patterns — not just their bio. Name their role/affiliation, dominant content themes, and what kind of audience follows them. Be specific: "DeFi yield strategist focused on Pendle and fixed-income protocols" is good. "Popular crypto influencer" is useless.

2. Campaign Fit (1-2 sentences): Connect this KOL's specific strengths to specific campaign goals from the brief above. Explain WHY their audience or content style serves the campaign — not just THAT they're relevant. Reference concrete signals from their tweets or bio.

Rules:
- Do NOT restate the bio verbatim. Synthesize from bio + tweet themes.
- Do NOT use generic praise ("great engagement", "large following").
- Each sentence must contain at least one specific detail (a project name, content style, audience type, or metric).
- Write in third person, professional tone, no emoji.
```

### Output Requirements

For each KOL, generate exactly two fields:

- **Profile** (1-2 sentences): Who they are — content focus, affiliations, audience type. Based on bio + tweet themes. Do NOT just restate the bio.
- **Campaign Fit** (1-2 sentences): Why they fit THIS specific campaign. Must reference specific campaign goals from the brief. Avoid generic praise.

### Fallback (No API Data)

If `api_available` is false or a KOL has an error:
- **Profile**: `[NO API DATA] @{handle}`
- **Campaign Fit**: `[NO API DATA] Manual review required`

## Step 4: CSV Compilation

Read the CSV format spec from `{skill_path}/references/csv-format.md`.

Assemble the CSV with these columns:
`No., KOL Name, Handle, Twitter, Followers, Est. Post Price (USD), Profile, Campaign Fit, Status, Notes`

Rules:
- `No.` = sequential starting from 1
- `KOL Name` = profile `name` field
- `Handle` = `@{screen_name}`
- `Twitter` = `https://x.com/{screen_name}`
- `Followers` = comma-formatted number in quotes
- `Est. Post Price (USD)` = "TBD" (unless user provides pricing)
- `Profile` = from Step 3 analysis, in quotes
- `Campaign Fit` = from Step 3 analysis, in quotes
- `Status` = "Pending"
- `Notes` = empty unless there's context

### Output Path

Default: `./{project}-kol-shortlist.csv` (current working directory).

If the user has a `Projects/ClientWork/{project}/proposals/` directory, offer to save there instead:
```
Projects/ClientWork/{project}/proposals/{Project} Campaign - KOL Shortlist.csv
```

If a file already exists at the chosen path, ask the user: overwrite or create a versioned file (append ` v2`, ` v3`, etc.)?

Write the CSV using Python's `csv` module for proper escaping:

```python
import csv
# Write rows using csv.writer to handle quoting correctly
```

## Step 5: Summary

Print a summary table:

```
KOL Shortlist Generated — {project}
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
 #  Name              Handle            Followers   Fit Preview
 1  Alice W.          @alice_web3       12,340      DeFi native, yield-focused...
 2  Bob DeFi          @bob_defi         89,608      Tier-1 reach, institutional...
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

Output: ./{project}-kol-shortlist.csv
KOLs: {total} ({success} with data, {failed} failed)
```
