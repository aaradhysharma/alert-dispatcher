# Alert Dispatcher — Architecture

> How the code is organized and what happens on each request.

---

## Layers

```
┌────────────────────────────────┐
│          HTTP Client           │  curl, another service
└───────────────┬────────────────┘
                │ POST /v1/dispatch
                │ POST /v1/mute | /v1/unmute
┌───────────────▼────────────────┐
│       api/dispatch.py          │  parse + validate, map errors to HTTP codes
│       api/mute.py              │
└───────────────┬────────────────┘
                │
┌───────────────▼────────────────┐
│    dispatch_service.py         │  orchestration (the brain)
│  ┌─────────┐  ┌─────────────┐  │
│  │users.py │  │  mute.py    │  │  user lookup + mute check
│  └─────────┘  └─────────────┘  │
│  ┌──────────┐  ┌────────────┐  │
│  │ email.py │  │  slack.py  │  │  send to each channel
│  └────┬─────┘  └────────────┘  │
└───────┼────────────────────────┘
        │ (on email failure only)
┌───────▼────────────────────────┐
│       retry.py  (SQLite)       │  store failed send for later retry
└────────────────────────────────┘
```

---

## Files at a glance

| File | What it does |
|------|--------------|
| `main.py` | Creates the FastAPI app; runs `init_db()` on startup. |
| `api/dispatch.py` | Thin HTTP adapter — validates body, maps unknown user → 404. |
| `api/mute.py` | Two routes: `POST /v1/mute` and `POST /v1/unmute`. |
| `services/dispatch_service.py` | Only place that knows the full order of operations. |
| `users.py` | Hardcoded user directory (email, Slack handle, channel prefs). |
| `repositories/mute.py` | In-memory `set[str]` of muted user IDs. |
| `repositories/retry.py` | SQLite table for failed email sends. |
| `providers/email.py` | Mock email sender. Masks recipient in logs. Raises on `FAIL`. |
| `providers/slack.py` | Mock Slack sender. Never logs the webhook path. |

---

## Request flow

1. **Request in** — caller sends `POST /v1/dispatch` with `user_id`, `event_type`, `payload`.
2. **Validation** — FastAPI checks the body automatically; missing/wrong fields → `422`.
3. **User lookup** — unknown `user_id` → `404`.
4. **Mute check** — user in mute set → return `status: "muted"`, skip all providers.
5. **Fan-out** — call each provider the user has configured.
6. **Email failure** — if email throws, write a row to the SQLite retry table and continue. Slack still fires.
7. **Response** — `"dispatched"` / `"partial_failure"` / `"muted"`. Provider failure never causes a `5xx`.

---

## Response status values

| `status` | Meaning |
|----------|---------|
| `"dispatched"` | All channels sent. |
| `"partial_failure"` | At least one channel failed; a `retry_id` is set on the failed channel. |
| `"muted"` | User is muted — no providers called. |
| `"no_op"` | User exists but has no channel preferences. |

---

## Safety rules

- **Emails masked** in all logs — `alice@example.com` → `a***@example.com`.
- **API keys logged as last 4 chars only** — `***key4`.
- **Slack webhook path never logged** — could contain an embedded token.
- **SQLite error messages truncated to 500 chars** — defence against keys in provider error strings.

---

## What is NOT in this version

| Missing piece | Reason |
|---------------|--------|
| Background retry worker | Retry *table* is fully implemented; the worker is a separate PR. |
| Durable mute storage | In-memory is fine for now; a lost mute is recoverable by re-muting. |
| Exponential backoff | Fixed 60 s window; changing it is a one-line edit in `record_email_failure`. |
