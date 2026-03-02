# kol-shortlist

Claude Code skill that generates Twitter-enriched KOL shortlist CSVs. Fetches real Twitter data via APIDance API, then uses Claude to write per-KOL Profile and Campaign Fit descriptions.

## Install

```bash
# 1. Clone into your .claude/skills/ directory
git clone https://github.com/yourorg/kol-shortlist.git .claude/skills/kol-shortlist

# 2. Run setup (creates venv, installs dependencies)
.claude/skills/kol-shortlist/setup.sh

# 3. Set your APIDance API key
export APIDANCE_API_KEY=your_key_here
```

## Register in CLAUDE.md

Add this snippet to your project's `CLAUDE.md` so Claude Code knows the skill exists:

```markdown
## Skill: `/kol-shortlist`

When the user says `/kol-shortlist {project}`, "generate KOL shortlist",
"create KOL list", or "build KOL CSV", execute the workflow defined in
`.claude/skills/kol-shortlist/SKILL.md`.
```

## Usage

In Claude Code, say any of:

- `/kol-shortlist MyProject`
- "generate KOL shortlist for MyProject"
- "build KOL CSV"

The skill will:
1. Ask for Twitter handles and campaign context
2. Fetch live Twitter data (profiles + recent tweets)
3. Generate per-KOL analysis (Profile + Campaign Fit)
4. Output a ready-to-use CSV

## Output

Default: `./{project}-kol-shortlist.csv` in your working directory.

## Requirements

- Python 3.9+
- APIDance API key (set as `APIDANCE_API_KEY` env var)
- Claude Code with skill support
