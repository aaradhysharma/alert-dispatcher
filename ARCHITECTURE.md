# Alert Dispatcher — Architecture (Plain English)

> A quick map of how the code is organized and what happens when a request arrives.
> For the interactive flow diagram, open the canvas: `alert-dispatcher-architecture.canvas.tsx`.

---

## Big picture

The service does one thing: receive an event and fan it out to notification channels (email, Slack, etc.) for the right user.

It was refactored from a single-file monolith into a small layered stack — each layer knows as little as possible about the others.

```
┌────────────────────────────────┐
│          HTTP Client           │  ← you, curl, another service
└───────────────┬────────────────┘
                │ POST /v1/dispatch
┌───────────────▼────────────────┐
│       api/dispatch.py          │  HTTP layer: parse, validate, 404/422
└───────────────┬────────────────┘
                │
┌───────────────▼────────────────┐
│    dispatch_service.py         │  Orchestration (the brain)
│  ┌─────────┐  ┌─────────────┐  │
│  │users.py │  │  mute.py    │  │  lookup + mute check
│  └─────────┘  └─────────────┘  │
│  ┌──────────┐  ┌────────────┐  │
│  │ email.py │  │  slack.py  │  │  send to each channel
│  └────┬─────┘  └────────────┘  │
└───────┼────────────────────────┘
        │ (on failure only)
┌───────▼────────────────────────┐
│       retry.py  (SQLite)       │  store for later retry
└────────────────────────────────┘
```

---

## Files and what they do

| File | In one sentence |
|------|-----------------|
| `main.py` | Creates the FastAPI app and sets up the SQLite retry table on startup. |
| `api/dispatch.py` | Thin HTTP adapter — validates the request body and maps "unknown user" to a 404. |
| `dispatch_service.py` | The only place that knows the full order of operations (see flow below). |
| `users.py` | A hardcoded list of users with their email, Slack handle, and channel preferences. |
| `repositories/mute.py` | An in-memory set of muted user IDs. Lives only while the process is running. |
| `providers/email.py` | Sends a mock email. Masks the recipient in logs. Raises an error if forced to fail. |
| `providers/slack.py` | Sends a mock Slack message. Never logs the webhook URL path (could contain a token). |
| `repositories/retry.py` | A SQLite table that records failed email sends so they can be retried later. |

---

## What happens on a normal request

1. **Request arrives** — a caller sends `POST /v1/dispatch` with `user_id`, `event_type`, and `payload`.
2. **Validation** — FastAPI checks the body automatically. Missing fields return `422` without any custom code.
3. **User lookup** — the service checks `users.py` for the user. Unknown ID → `404`.
4. **Mute check** — if the user is in the mute set, return `status: "muted"` immediately, skip all providers.
5. **Fan-out** — for each channel the user wants, call the matching provider.
6. **Email failure?** — if the email provider throws, write a row to the SQLite retry table and keep going. Slack still fires.
7. **Response** — return `"dispatched"`, `"partial_failure"`, or `"muted"`. A provider failure never causes a `5xx`.

---

## Response status values

| `status` | Meaning |
|----------|---------|
| `"dispatched"` | All channels sent successfully. |
| `"partial_failure"` | At least one channel failed; the rest were sent. A `retry_id` is included for each failure. |
| `"muted"` | User is muted — no providers were called. |
| `"no_op"` | User exists but has no channel preferences configured. |

---

## Safety rules baked into the code

- **Email addresses are always masked** before they appear in any log line (`alice@example.com` → `a***@example.com`).
- **API keys are logged only as the last 4 characters** (`***key4`).
- **Slack webhook paths are never logged** — the webhook URL can embed a token in the path, so only the host is logged.
- **SQLite error messages are truncated to 500 chars** as a defence against upstream providers that might include a key in their error string.

---

## What is NOT in this version (and why)

| Missing piece | Reason it was left out |
|---------------|------------------------|
| Background retry worker | The retry *table* and helpers are fully implemented; the worker is a separate concern and a separate PR. |
| Durable mute storage | In-memory is enough for the exercise; a lost mute is recoverable by re-muting. |
| Admin API for muting | The repository functions are the internal surface for now; a router can expose them later without a refactor. |
| Exponential backoff | Fixed 60-second window for now; changing it is a one-line edit to `record_email_failure`. |
