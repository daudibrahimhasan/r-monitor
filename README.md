# Reddit Intent Lead Engine (Zero-$0 stack)

This project searches Reddit for high-intent posts, scores them, extracts public contact routes, drafts outreach, and optionally sends only compliant emails.

Key safety rules:
- No identity matching (for example Reddit username to LinkedIn to guessed email).
- Only email when the email is publicly present in the post or on a website the post links to.
- Default mode is draft-only; sending requires explicit opt-in.

## Quickstart

1. Create your config:
- Edit `config.yaml` for business leads.
- Edit `research/config.yaml` for research collaboration leads.

2. Run draft-only:
- `python -m reddit_intent_engine.main`
- `python -m reddit_intent_engine.main --config reddit_intent_engine/config.yaml`
- `python -m reddit_intent_engine.main --config reddit_intent_engine/research/config.yaml`

3. If you want to enable sending for business leads:
- Set `email.enabled: true` in config.
- Provide SMTP credentials, ideally via env var.
- Run with `--send`.

## Outputs

- Business DB: `data/leads.sqlite`
- Business log: `data/logs.txt`
- Business exports: `data/exports/`
- Research DB: `research/data/research_leads.sqlite`
- Research log: `research/data/logs.txt`
- Research exports: `research/data/exports/research_leads.md` and `research/data/exports/research_leads.csv`

## Scheduler (Windows)

Use Task Scheduler to run `scheduler.ps1` hourly. Research mode should be scheduled separately with `--config reddit_intent_engine/research/config.yaml`.
