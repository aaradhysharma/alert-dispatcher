# AI-assisted work: what to include in your submission

We allow AI tools. We still need evidence of **your** engineering judgment.

## Required when AI was used

Add a section to `SUBMISSION.md` (or attach separate files) with:

1. **Tooling:** Which product(s) (for example ChatGPT, Claude, Cursor, Copilot) and approximate share of AI-generated vs hand-edited lines.

	I used cursor mostly model auto for small task. and claude 4.6 for medium and 4.7 for large task. 
along with that I used its agent too. hand edit:- 5% I initially started looking at monolith i change the alert as all were set to 500 easy to set alert code 

2. **Prompts summary:** The *intent* of major prompts (not full logs unless you already have them), especially for refactors and tests.

	I first used cursor ask mode first to analyse entire project, generate me some diagrams to understand workflow. 
then ask cursor to suggest architecture meanwhile I asked claude separately for the same. I asked cursor for multiple skeleton approach and pipeline approach than selected modified its given workflow suggest it edit than move to plan mode. 
cursor was overcomplicating the architecture which can break the system I suggest it to keep it simple and understandable. 

3. **What you rejected:** At least one AI suggestion you **did not** take, and why.

	cursor suggested generic DB for output for failed request I told cursor (model 4.6 sonnet) that this is wrong and there should be proper table where data is stored and it should be easily be human readable and should contain columns like primary, userid time stamp, email etc. and gave it pseudo code to kit to create proper table.

4. **Verification:** Commands you ran locally (`pytest`, `ruff`, manual `curl`) after AI edits.

I used WSL for this as I am more familiar with Linux commands. 

	I did manually run in my WSL 
in new terminal after pytest -v > pytest-result.txt 2>&1. 
I had asked cursor to place several test cursor, cursor added lots of tests with edge cases I ask it to reduce it so code is more defensible. final test number are 25.
than I myself created GitHub action file to make testing easier so after each small update my code( commit and sync) testing is done automatically and I dont have to run pytest command again and again.

I also tested if my table is being populated by curl the test that cursor did created over engineered test but it doesn't create a simple test that check if db is getting populated. 
I used simple curl to check.

```bash
curl -sS -X POST http://127.0.0.1:8000/v1/dispatch \
  -H 'Content-Type: application/json' \
  -d '{"user_id":"user-2","event_type":"PleaseFAIL","payload":{}}'
```

and

```bash
curl -sS -X POST http://127.0.0.1:8000/v1/dispatch \
  -H 'Content-Type: application/json' \
  -d '{"user_id":"user-1","event_type":"EmailFAIL","payload":{"note":"demo"}}'
```

finaly I asked claude code to audit. entire project.

- Export or paste a `CLAUDE.md` / `AGENTS.md` / `.cursor/rules` style file if you used project-specific AI instructions — this helps reviewers separate intentional constraints from model drift.

## `.cursor/rules/`

Here is my cursor rule file.

### Pseudo code for rules

```text
stack-  use python3, pydantic v2, pydantic setting sql lite for now. 

don't touch :- setting.py , .env.example,pyproject.toml

log:- Imp 
- dont log full api key ever, 
- make sure to mask emails 

test
all behaviour change test ,mock email/slack, mute user, bad input happy path.
working style:- no monilith small diff,  tradeoff needs to be explained, dont produce code that is too complex and write comment thoroughly to explain.
```

### Using cursor feature to modify your cursor rules file to be more comprehensive

```text
# Alert Dispatcher Project Standards

## Stack

- Python 3, Pydantic v2, `pydantic-settings`
- SQLite for now (do not introduce another DB without explicit ask)

## Do Not Touch

These files are owned/locked. Do not edit unless explicitly asked:

- `settings.py`
- `.env.example`
- `pyproject.toml`

If a change seems required there, stop and ask first.

## Logging (Important)

- **Never log full API keys.** Log only the last 4 chars, prefixed with `***`.
- **Always mask emails** before logging.

```python
# bad
logger.info(f"using key {api_key}")
logger.info(f"sending to {user.email}")

## good
logger.info(f"using key ***{api_key[-4:]}")
logger.info(f"sending to {mask_email(user.email)}")  # a***@example.com
```

## Tests

- Behaviour-changing tests run in GitHub Actions and may hit real email/Slack.
- For each behaviour change, cover: **happy path, bad input, muted user**.

## Working Style

- **No monolith diffs.** Ship small, focused PRs — one concern per diff.
- **Explain tradeoffs** in the PR/chat message whenever a non-obvious choice is made (e.g. SQLite vs Postgres, sync vs async).
- **Don't write overly clever code.** Prefer readable over compact.
- **Comment thoroughly** — explain *why*, not *what*. Especially around retries, masking, rate limits, and any external I/O.
```

*** note both submisson.md and ai-submission.md are written in extremely natural language for transparency they are in now way shape or form reflect actual prodcution documenttation standards.

## Integrity

Paste-polished code you cannot explain in review is a strong negative signal. Prefer smaller, understandable diffs you own end-to-end.
