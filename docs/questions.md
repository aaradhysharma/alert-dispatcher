# Candidate brief: Professionalization sprint (≈2 hours)

## Context

You are handed a prototype “Alert Dispatcher” built under time pressure. Product and infra agree it is **not** production-ready. Your job is to move it toward something you would be comfortable operating on a small internal service.

The current HTTP surface is documented in the running app at `/docs`. The implementation lives mainly in `src/alert_dispatcher/api/intern_monolith.py`.

## Timebox and priorities

Target **~2 hours**. We value **clear trade-offs and working software** over feature count. If you run short on time, write down what you would do next and why.

## Tasks

### 1. Refactor for maintainable structure

Move domain logic, provider integrations, and HTTP concerns toward a structure you would defend in code review. The starting point is deliberately monolithic.

**Expected outcome (for review):** Briefly explain (in `SUBMISSION.md` at repo root or as a PR description) how you split responsibilities and what you would **not** change in a second timebox.

### 2. Mute list

Implement a **mute list**: if a user is muted, the system must **not** send any notifications for that user.

- You may store muted user IDs in memory, a file, or a database — justify your choice in your submission notes.
- Behavior must be **testable** without real email or Slack (mock or fake providers are fine).

**Expected outcome:** Callers hitting `POST /v1/dispatch` for a muted user receive a **clear, intentional HTTP response** (you pick the status code and body shape, but document it in `SUBMISSION.md`).

### 3. Resiliency gotcha — mock email failures

The mock email provider can fail when the **notification subject or serialized payload**
contains the substring `FAIL` (case-insensitive). This is intentional for demos.

**Required behavior after your changes:**

1. When mock email fails, the API must **not crash** with an unhandled `500` solely because of that provider failure.
2. The failure must be **logged** with enough context to debug (without logging secrets such as API keys in plain text).
3. A record of the failure must be **persisted for retry** (a simple “retry table” or queue is enough — SQLite is fine).

**Expected outcome:** Describe your retry semantics (at minimum: what fields you store and what a future worker would do). If you do not implement a background worker, explain how your design keeps the HTTP path responsive.

## Optional pivot (5–10 minutes)

If the interviewer sends this mid-session, incorporate it:

> Legal asks that we **never** store raw email addresses in application logs. Mask emails in logs (for example `j***@example.com`).

## AI tools

If you used an AI assistant, read [`docs/ai-submission.md`](ai-submission.md) and include the listed artifacts with your submission.

## What to deliver

- Your branch or patch with code changes.
- `SUBMISSION.md` covering: architecture notes, how to run tests, known limitations, and AI disclosure (if applicable).

## Clarifications

If requirements conflict or data is missing, state your assumptions in `SUBMISSION.md` and proceed with the smallest reasonable default.
