# Alert Dispatcher (Interview Exercise)

Baseline **FastAPI** service that receives events and fans them out to mock notification channels. The codebase is intentionally rough so candidates can demonstrate refactoring, testing, and production-minded behavior in a short session.

Mock provider credentials are read from the environment (see **Configuration**); only `.env.example` is committed, so you can share or push this repository without embedding secrets in source files.

Full assignment text lives in [`docs/questions.md`](docs/questions.md). 

## Prerequisites

- Python **3.11+**
- A virtual environment tool (`venv` is enough)

## Configuration (secrets)

Provider credentials are **not** in the repository. Copy the example env file and set your own local or sandbox values:

```bash
cp .env.example .env
# Edit .env — never commit real keys (`.env` is gitignored)
```

| Variable | Purpose |
|----------|---------|
| `MOCK_EMAIL_API_KEY` | Mock email provider key (used for logging a short suffix only) |
| `MOCK_SLACK_WEBHOOK` | Mock Slack incoming webhook URL |

You can also export these variables in your shell instead of using a `.env` file. The app loads `.env` from the **current working directory** when you start `uvicorn`, so run commands from the repository root unless you rely on exported env vars only.

## Quick start

```bash
cd interview-exercise
python3 -m venv .venv
source .venv/bin/activate   # Windows: .venv\Scripts\activate
pip install -U pip
pip install -e ".[dev]"
```

Set `MOCK_EMAIL_API_KEY` and `MOCK_SLACK_WEBHOOK` using a `.env` file or your shell (see [Configuration](#configuration-secrets) above).

Run the API:

```bash
uvicorn alert_dispatcher.main:app --reload --host 0.0.0.0 --port 8000
```

Open interactive docs: [http://127.0.0.1:8000/docs](http://127.0.0.1:8000/docs)

### Smoke request

```bash
curl -sS -X POST http://127.0.0.1:8000/v1/dispatch \
  -H 'Content-Type: application/json' \
  -d '{"user_id":"user-1","event_type":"UserSignedUp","payload":{"plan":"pro"}}' | jq .
```

Health check:

```bash
curl -sS http://127.0.0.1:8000/health
```

### Optional quality commands

```bash
ruff check src tests
pytest
```

There are **no** meaningful tests in the baseline; adding them is part of what we look for at mid level and above.

## Project layout

| Path | Purpose |
|------|---------|
| `src/alert_dispatcher/` | Application package |
| `src/alert_dispatcher/settings.py` | Environment-backed settings (`MOCK_*` from `.env`) |
| `src/alert_dispatcher/api/intern_monolith.py` | **Baseline “intern” implementation** — do not treat as a model to copy |
| `docs/questions.md` | Candidate-facing brief and acceptance-style expectations |
| `docs/answers.md` | Interviewer evaluation guide (do not share with candidates if you prefer) |
| `docs/ai-submission.md` | What to submit when AI tools were used |
| `.env.example` | Template for required environment variables (no secrets) |

## Seed users

`user-1`, `user-2`, and `user-3` are defined in `intern_monolith.py` with different channel preferences. Unknown `user_id` values return `404`.

## License

Internal hiring exercise — not for public redistribution unless your organization permits it.
