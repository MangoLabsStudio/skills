# KOL Shortlist CSV Format

## Columns

| # | Column | Description |
|---|--------|-------------|
| 1 | No. | Sequential number |
| 2 | KOL Name | Display name from Twitter profile |
| 3 | Handle | @username |
| 4 | Twitter | Full URL: `https://x.com/{handle}` |
| 5 | Followers | Follower count, comma-formatted (e.g., "38,076") |
| 6 | Est. Post Price (USD) | Estimated cost per post, or "TBD" |
| 7 | Profile | 1-2 sentences: content focus, affiliations, audience type |
| 8 | Campaign Fit | 1-2 sentences: specific reasons this KOL fits THIS campaign |
| 9 | Status | Default: "Pending" |
| 10 | Notes | Optional: "Retained from previous list", special context |

## Example Row

```csv
No.,KOL Name,Handle,Twitter,Followers,Est. Post Price (USD),Profile,Campaign Fit,Status,Notes
1,Alice W.,@alice_web3,https://x.com/alice_web3,"12,340","TBD","DeFi yield strategist and early Pendle contributor. Content focuses on fixed-income protocols and LP optimization for a technically savvy audience.","Deep expertise in yield narratives aligns with campaign's fixed-income positioning. Authentic voice in the target protocol community, not a generalist shill.",Pending,
```

## Rules

- Wrap `Followers` in quotes when comma-formatted
- Wrap `Profile` and `Campaign Fit` in quotes (they contain commas/punctuation)
- `Est. Post Price` is "TBD" unless known; use "$X,XXX" format when available
- `Status` is always "Pending" for new shortlists
- `Notes` is empty by default
