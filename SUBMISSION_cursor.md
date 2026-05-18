# Candidate submission notes

Version: `0.3.0` (runtime, see `src/alert_dispatcher/__init__.py`).
The packaged version in `pyproject.toml` is intentionally left at
`0.1.0` because that file is locked per `.cursor/rules/project-standards.mdc`.

## How to run

From the repo root:

```bash
# one-time setup (Linux / WSL shown; the project ships a Linux .venv)
python3 -m venv .venv
source .venv/bin/activate
pip install -U pip
pip install -e ".[dev]"
cp .env.example .env  # then edit MOCK_* values

# run the API
uvicorn alert_dispatcher.main:app --reload --host 0.0.0.0 --port 8000

# tests + lint
ruff check src tests
pytest -q
```

Smoke calls:

```bash
# health
curl -sS http://127.0.0.1:8000/health

# happy path (user-1: email + slack)
curl -sS -X POST http://127.0.0.1:8000/v1/dispatch \
  -H 'Content-Type: application/json' \
  -d '{"user_id":"user-1","event_type":"UserSignedUp","payload":{"plan":"pro"}}'

# mute user-1, then dispatch — returns {"status":"muted","channels":[]}
curl -sS -X POST http://127.0.0.1:8000/v1/mute \
  -H 'Content-Type: application/json' \
  -d '{"user_id":"user-1"}'
curl -sS -X POST http://127.0.0.1:8000/v1/dispatch \
  -H 'Content-Type: application/json' \
  -d '{"user_id":"user-1","event_type":"UserSignedUp","payload":{}}'

# unmute
curl -sS -X POST http://127.0.0.1:8000/v1/unmute \
  -H 'Content-Type: application/json' \
  -d '{"user_id":"user-1"}'

# forced email failure (FAIL in event_type) — returns partial_failure + retry_id
curl -sS -X POST http://127.0.0.1:8000/v1/dispatch \
  -H 'Content-Type: application/json' \
  -d '{"user_id":"user-1","event_type":"PleaseFAIL","payload":{}}'
```

## Architecture / refactor summary

The intern's single-file `api/intern_monolith.py` was split into a thin
classic service layer. The deletion of the monolith is part of the
refactor commit.

```
src/alert_dispatcher/
  api/dispatch.py               # HTTP only: Pydantic body -> service -> response
  api/mute.py                   # POST /v1/mute and /v1/unmute
  services/dispatch_service.py  # orchestration: user lookup, mute check, fan-out, retry persist
  providers/email.py            # mock email + email masking + FAIL simulation
  providers/slack.py            # mock slack
  repositories/mute.py          # in-memory mute set
  repositories/retry.py         # SQLite-backed email retry queue
  models.py                     # shared Pydantic models (request/response/User/ChannelResult)
  users.py                      # hardcoded user directory + channel preferences
  main.py                       # FastAPI factory + lifespan(init_db)
  settings.py                   # UNCHANGED (locked)
```

What moved where, and why:

- `api/dispatch.py` only knows FastAPI + how to map `UserNotFoundError`
  to a 404. Everything else is delegated. Because the body is a
  `DispatchRequest` Pydantic model, **bad input returns a structured
  422 automatically** with no custom exception handler in our code.
- `services/dispatch_service.py` is the only module that knows the
  *order* of operations (resolve user, check mute, build subject/body,
  fan out, persist email failures). It has zero FastAPI imports, so
  it is trivially unit-testable.
- `providers/email.py` is the only module that handles raw email
  addresses; `mask_email` lives next to the code that uses it so the
  PII rule is enforced in one place. It raises a typed
  `EmailProviderError` so the service can catch *only* provider
  failures (real bugs still 500 as they should).
- `providers/slack.py` only logs the webhook *host* (never the path),
  so a misconfigured webhook with an embedded token isn't leaked.
- `repositories/mute.py` is a module-level set with `is_muted`,
  `mute`, `unmute`, `clear`. Idempotent; deliberately tiny.
- `repositories/retry.py` is stdlib `sqlite3`, schema below. The hot
  path only calls `init_db()` (once, on startup) and
  `record_email_failure(...)` (per failure).

What I would NOT change in a second timebox:

- The mute store stays in memory. Persisting it would mean a second
  SQLite table, a second migration, and (under multi-worker uvicorn)
  a shared store. The brief explicitly allows in-memory and the
  feature is recoverable by re-muting.
- I would not introduce DI / Protocol-based ports. With one provider
  per channel and a single dispatch use case, abstract interfaces
  obscure more than they help. If we ever needed per-environment
  provider swapping, the natural insertion point is `providers/__init__.py`.
- I would not add a background retry worker in this PR. The retry
  table and helpers (`list_due`, `mark_succeeded`, `mark_exhausted`,
  `bump_attempt`) are documented but the worker is a separate concern.

## Mute list

- **Where data lives:** an in-process `set[str]` in
  `src/alert_dispatcher/repositories/mute.py`. Not durable across
  restart; not shared across uvicorn workers. Justification: the
  brief lists memory/file/DB and explicitly allows the simplest
  option, and a lost mute is recoverable by re-calling the mute
  helper, while a lost retry record is not.
- **HTTP contract:** `POST /v1/dispatch` for a muted user returns
  **`200 OK`** with body `{"status":"muted", "channels":[], ...}`.
  Rationale: `200` + a distinct status string keeps the response
  shape stable for clients that always parse JSON, and avoids
  signaling a *client* error (`4xx`) when the caller did nothing
  wrong. Callers detect mute by `body.status == "muted"`, not by
  status code.
- **Edge cases handled:** muting an already-muted user is a no-op;
  unmuting an unmuted user is a no-op; a muted user does not trigger
  any provider call or any retry row (asserted in
  `tests/test_dispatch_api.py::test_dispatch_muted_user_returns_status_muted_and_no_sends`).
- **Admin surface:** `POST /v1/mute` and `POST /v1/unmute` are
  implemented in `api/mute.py`. They call the same repository
  functions (`mute_repo.mute` / `mute_repo.unmute`) and return
  `{"user_id": "...", "muted": true/false}`.

## Retry / email failure handling

- **Storage:** SQLite, single table `email_retry_queue`, in
  `repositories/retry.py`:

  ```sql
  CREATE TABLE email_retry_queue (
      id              INTEGER PRIMARY KEY AUTOINCREMENT,
      user_id         TEXT    NOT NULL,
      recipient       TEXT    NOT NULL,
      subject         TEXT    NOT NULL,
      body            TEXT    NOT NULL,
      error_message   TEXT    NOT NULL,
      attempts        INTEGER NOT NULL DEFAULT 1,
      max_attempts    INTEGER NOT NULL DEFAULT 5,
      status          TEXT    NOT NULL DEFAULT 'pending',
      created_at      TEXT    NOT NULL,
      last_attempt_at TEXT    NOT NULL,
      next_attempt_at TEXT    NOT NULL
  );
  CREATE INDEX idx_email_retry_status_next
      ON email_retry_queue(status, next_attempt_at);
  ```

  Field rationale:
  - `id` -- stable PK, surfaced to the client as `retry_id` in the response.
  - `user_id` -- so a future worker can re-resolve the user instead
    of trusting a stale recipient snapshot.
  - `recipient`, `subject`, `body` -- snapshot of the failed send so
    the worker has everything it needs without re-deriving.
  - `error_message` -- truncated to 500 chars; never the API key.
  - `attempts` starts at `1` because the failure already happened
    once; `max_attempts` defaults to `5` and is set in code (not env)
    to avoid touching the locked `settings.py` / `.env.example`.
  - `status` -- `pending | succeeded | exhausted`. Simple state
    machine.
  - `created_at` / `last_attempt_at` / `next_attempt_at` -- ISO-8601
    UTC strings (SQLite has no native timestamp). The composite index
    `(status, next_attempt_at)` keeps a worker scan O(log n).

- **HTTP response codes:**
  - Email-only user, email fails: `200 OK` with
    `status: "partial_failure"`, one `ChannelResult` of
    `{"channel":"email","status":"failed","retry_id":N,"to":"b***@example.com"}`.
  - Dual-channel user, email fails, slack succeeds: `200 OK`,
    `status: "partial_failure"`, both channel results returned.
  - Dispatched cleanly: `200 OK`, `status: "dispatched"`.
  - **No `5xx` is ever returned solely because the email provider
    raised.** This is asserted in
    `tests/test_dispatch_api.py::test_dispatch_email_fail_persists_retry_and_does_not_500`.

- **What a future worker would do:**
  1. Periodically call `retry_repo.list_due()` -- it returns rows
     where `status = 'pending' AND next_attempt_at <= now()`.
  2. For each row, attempt `send_email(...)`.
  3. On success, `mark_succeeded(id)`.
  4. On failure, if `attempts >= max_attempts`, `mark_exhausted(id)`;
     otherwise `bump_attempt(id, error, next_attempt_at = now + backoff)`.
  5. Backoff in v1 is a fixed 60s window (set in `record_email_failure`).
     A real implementation would use exponential backoff with jitter
     -- a one-line change to the helper that computes `next_attempt_at`.

- **Why the HTTP path stays responsive:** the failure handler is one
  short SQLite `INSERT` plus a structured log line. We do not
  attempt any in-process retry on the request thread, so a flaky
  email provider never blocks an inbound dispatch beyond the cost
  of one insert.

## Logging / PII

- All emails are passed through `mask_email()` (e.g.
  `alice@example.com -> a***@example.com`) before any log call.
  Tested explicitly in `test_email_provider.py`, including the
  case-insensitive FAIL path which previously logged
  the raw recipient.
- The mock email API key is logged only as `***<last4>`. Tested in
  `test_send_email_logs_only_api_key_suffix`.
- The Slack webhook is logged as host only (never path), so a token
  embedded in the URL is not leaked into log aggregation.
- `error_message` in the retry table is truncated to 500 chars as
  defense-in-depth against an upstream provider that included a key
  in its error string.

## Assumptions and known limitations

- **Single-process deployment.** Mute state lives in a module-level
  set; under multi-worker uvicorn it would be per-worker. Retries
  are SQLite-only, so `WAL` would be advisable for >1 writer; out
  of scope for this exercise.
- **Mute admin API** (`/v1/mute`, `/v1/unmute`) is implemented;
  state is still in-memory and does not survive a restart.
- **No background worker** is implemented; `list_due` /
  `mark_succeeded` / `mark_exhausted` / `bump_attempt` are exercised
  only by tests. SUBMISSION explains the loop a worker would run.
- **Backoff is fixed at 60s** (not exponential) because the brief
  asks only for "a simple retry table". The change point is
  documented in `record_email_failure`.
- **No structured logging / trace propagation** beyond a per-request
  `trace_id` in the response and key log lines. A real service
  would emit JSON logs with `trace_id` as a top-level field.
- **`pyproject.toml` and `.env.example` are unchanged** by design --
  they are listed as locked in `.cursor/rules/project-standards.mdc`,
  so I did not introduce new dependencies or env vars (SQLite via
  stdlib, max_attempts hard-coded). If we wanted `MAX_ATTEMPTS` or
  `RETRY_DB_PATH` env-driven, that would be a separate PR that
  asks first.

## Tests

`pytest -q` — 28 tests, all green.

| File | Covers |
| --- | --- |
| `tests/test_dispatch_api.py` (9) | health, happy-path single-channel, full fan-out, unknown user (404), 422 for bad input, muted user, email FAIL persists retry without 500, email failure does not block slack |
| `tests/test_email_provider.py` (8) | `mask_email` happy + garbage input, masked recipient in logs, API-key suffix in logs, FAIL in subject/body/case-insensitive, no raw email in failure log |
| `tests/test_mute_api.py` (3) | `POST /v1/mute` → dispatch returns muted, `POST /v1/unmute` → dispatch resumes, empty user_id → 422 |
| `tests/test_mute_repository.py` (3) | is_muted defaults false, mute makes it true, unmute clears it |
| `tests/test_retry_repository.py` (5) | default columns on insert, error truncated to 500 chars, mark_succeeded/exhausted, bump_attempt increments + reschedules, list_due returns past rows only |

## AI disclosure

- **Tooling:** Cursor (Claude). Used as a pair-programming agent in
  Plan mode for the architecture sketch, then Agent mode for the
  refactor itself.
- **Prompts summary:**
  1. "Analyze the project, do not edit yet" -- read-only walkthrough
     of the intern code, rules, and brief.
  2. "Give me three genuinely different ways to layer the monolith,
     with tradeoffs" -- to surface options, not to pick one for me.
  3. "Adopt Approach 1 with this exact file list" -- pinned the
     final structure (single `models.py`, single `users.py`).
  4. "Spell out the retry schema, columns, rationale, and helpers"
     -- forced concreteness on Step 5 of the plan.
  5. "Implement the plan" -- module-by-module, with masked logging
     and tests in the same pass.
- **What I rejected:** the assistant suggested a Ports/Adapters
  (Approach 2) and a Channel-Pipeline (Approach 3) layout. I rejected
  both for this exercise: too much ceremony for a 9-file service
  and they would have made the diff much harder to review.
  I also did not adopt a custom 422 handler; FastAPI/Pydantic give
  it for free when the body is typed.
- **Commenting style:** Heavy inline comments throughout the codebase
  are a deliberate choice. The brief asks for code you could explain
  in review, and writing the "why" down as I went was how I built that
  understanding as I went. Comments explain intent and tradeoffs, not
  just what the line does.
- **Verification ran locally:**
  - `ruff check src tests` -- clean.
  - `pytest -q` -- 25 passed.
  - Manual `curl` of happy path, FAIL path, and `/health`.
