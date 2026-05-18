# Alert Dispatcher

FastAPI service that receives events and fans them out to notification channels (email, Slack).

## Prerequisites

- Python **3.11+**

## Setup

```bash
python3 -m venv .venv
source .venv/bin/activate       # Windows: .venv\Scripts\activate
pip install -U pip
pip install -e ".[dev]"
cp .env.example .env            # set MOCK_EMAIL_API_KEY and MOCK_SLACK_WEBHOOK
```

## Run

```bash
uvicorn alert_dispatcher.main:app --reload --host 0.0.0.0 --port 8000
```

Interactive docs: [http://127.0.0.1:8000/docs](http://127.0.0.1:8000/docs)

## Test & lint

```bash
ruff check src tests
pytest -q
```

## Smoke curls

```bash
# health
curl -sS http://127.0.0.1:8000/health

# dispatch (user-1 has email + slack)
curl -sS -X POST http://127.0.0.1:8000/v1/dispatch \
  -H 'Content-Type: application/json' \
  -d '{"user_id":"user-1","event_type":"UserSignedUp","payload":{"plan":"pro"}}'

# mute a user
curl -sS -X POST http://127.0.0.1:8000/v1/mute \
  -H 'Content-Type: application/json' \
  -d '{"user_id":"user-1"}'

# dispatch again — returns {"status":"muted","channels":[]}
curl -sS -X POST http://127.0.0.1:8000/v1/dispatch \
  -H 'Content-Type: application/json' \
  -d '{"user_id":"user-1","event_type":"UserSignedUp","payload":{}}'

# unmute
curl -sS -X POST http://127.0.0.1:8000/v1/unmute \
  -H 'Content-Type: application/json' \
  -d '{"user_id":"user-1"}'

# force email failure (FAIL anywhere in event_type)
curl -sS -X POST http://127.0.0.1:8000/v1/dispatch \
  -H 'Content-Type: application/json' \
  -d '{"user_id":"user-1","event_type":"PleaseFAIL","payload":{}}'
```

## API endpoints

| Method | Path | What it does |
|--------|------|--------------|
| `GET` | `/health` | Liveness check |
| `POST` | `/v1/dispatch` | Fan out an event to a user's channels |
| `POST` | `/v1/mute` | Add a user to the mute list |
| `POST` | `/v1/unmute` | Remove a user from the mute list |

## Seed users

| User | Email | Slack | Channels |
|------|-------|-------|----------|
| `user-1` | alice@example.com | @alice | email + slack |
| `user-2` | bob@example.com | @bob | email only |
| `user-3` | carol@example.com | @carol | slack only |

Unknown `user_id` → `404`.

## Project layout

| Path | Purpose |
|------|---------|
| `src/alert_dispatcher/api/dispatch.py` | HTTP handler for `/v1/dispatch` |
| `src/alert_dispatcher/api/mute.py` | HTTP handlers for `/v1/mute` and `/v1/unmute` |
| `src/alert_dispatcher/services/dispatch_service.py` | Orchestration logic |
| `src/alert_dispatcher/providers/email.py` | Mock email sender + PII masking |
| `src/alert_dispatcher/providers/slack.py` | Mock Slack sender |
| `src/alert_dispatcher/repositories/mute.py` | In-memory mute set |
| `src/alert_dispatcher/repositories/retry.py` | SQLite retry queue for failed emails |
| `src/alert_dispatcher/users.py` | Hardcoded user directory |
| `src/alert_dispatcher/models.py` | Shared Pydantic models |
| `docs/questions.md` | Candidate-facing brief |
| `.env.example` | Template for environment variables (no secrets) |

## Configuration

| Variable | Purpose |
|----------|---------|
| `MOCK_EMAIL_API_KEY` | Mock email provider key |
| `MOCK_SLACK_WEBHOOK` | Mock Slack incoming webhook URL |

## CI

GitHub Actions (`.github/workflows/test.yml`) runs `ruff check` and `pytest` on every push, pull request, and manual trigger (`gh workflow run "Tests"`).
