# research-project

Claude Code skill that auto-discovers and batch-downloads all public information about a crypto/web3 project — docs, blogs, GitHub repos, media coverage, and Twitter/X presence.

## Install

```bash
# 1. Clone into your .claude/skills/ directory
git clone https://github.com/yourorg/research-project.git .claude/skills/research-project

# 2. Run setup (creates venv, installs deps + Playwright Chromium)
.claude/skills/research-project/setup.sh

# 3. (Optional) For Twitter data, also install kol-shortlist as a sibling skill
git clone https://github.com/yourorg/kol-shortlist.git .claude/skills/kol-shortlist
.claude/skills/kol-shortlist/setup.sh
export APIDANCE_API_KEY=your_key_here
```

## Sibling Skill Dependency

Twitter fetching (Steps 5-6) requires the `kol-shortlist` skill installed at `.claude/skills/kol-shortlist/`. If not present, the skill works fine — it just skips Twitter analysis.

## Register in CLAUDE.md

```markdown
## Skill: `/research-project`

When the user says `/research-project {project}`, "research project", "抓项目资料",
or "collect project info", execute the workflow defined in
`.claude/skills/research-project/SKILL.md`.
```

## Usage

```
/research-project ExampleDAO
```

The skill will:
1. Discover all public links from the project's website
2. Show you what it found, let you filter
3. Batch-scrape docs, blogs, GitHub, media coverage
4. Fetch Twitter data and generate analysis (if kol-shortlist is installed)
5. Output everything to `./{project}-research/` or your project's `research/` directory

## Requirements

- Python 3.9+
- `gh` CLI (authenticated, for GitHub repo scraping)
- Playwright Chromium (installed by setup.sh)
- APIDance API key (optional, for Twitter — set as `APIDANCE_API_KEY`)
- `kol-shortlist` sibling skill (optional, for Twitter fetching)
