# Candidate submission notes

Replace this file with your own write-up before the review. Remove sections you do not need.

## How to run

Used WSL.

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -U pip
pip install -e ".[dev]"
cp .env.example .env        # put value in mock field
```

Running API:

```bash
uvicorn alert_dispatcher.main:app --reload --host 0.0.0.0 --port 8000
```

Test:

```bash
ruff check src tests
pytest -q
```

Optional for GitHub action (you need `gh` installed and signed in, otherwise you can just commit and sync). Tests will run automatically.

## Smoke test

### Normal send

```bash
# normal send
curl -sS -X POST http://127.0.0.1:8000/v1/dispatch \
  -H 'Content-Type: application/json' \
  -d '{"user_id":"user-1","event_type":"UserSignedUp","payload":{"plan":"pro"}}'
```

### Forced email failure (any event with "FAIL" in it, case-insensitive)

```bash
# forced email failure (any event with "FAIL" in it, case-insensitive)
curl -sS -X POST http://127.0.0.1:8000/v1/dispatch \
  -H 'Content-Type: application/json' \
  -d '{"user_id":"user-2","event_type":"PleaseFAIL","payload":{}}'
```

### Health

```bash
# health
curl -sS http://127.0.0.1:8000/health
```

## Architecture / refactor summary

What moved where, and why:

**Refactor summary**

`api/dispatch.py`: this is just web layer only job is to take incoming request and it will return a response. this py doesn't make any decisions. it will give unknown user into 404.

`services/dispatch_service.py`: this is our main file it sets up order of things, lookup user, check if users are muted it also finds their channels, it buils the message, which it sends to each channel. it also builds the response, it doesn't have a working web framework imports, so we can actually test it without starting a server.

`providers`: `emails.py` & `slack.py`. these are actually send notifications, the email.py is specially seprated and isolated on purpose, so the raw email address privacy rul is enforced only there.

`repository`: `mute.py` and `retry.py` these are data storage mute lives in memory, retry lives in proper DB file (SQLite). I would scale it to postgres in prod.

`users.py`: for prod purpose this will be a db as of now its just hardcoded list of users.

`main.py`: this file create the app and SQl lite table.

## Mute list

**Mute list** is at repository, `repositories/mutes.py` and I also created api endpoint to mute and unmute the user at `api/mute.py` (this is going against cursor decision for simplify testing and presentation).

My understanding is muted user should not get notification.

It has function: `is_muted`, `mute`, `unmute`, `clear`.

The repo has function: `is_muted`, `mute`, `unmute`, `clear`.

Workflow goes `POST /v1/dispatch` for muted user will return us 200 OK.

My choice was not to return an error code as technichally its not called fault that user is muted, and 400ish error can be misleading.

But in return caller will get status `muted`.

I added manual endpoint so a user can be muted and umuted from running server without restarting and keep editing code.

Firstly to test we just mute a user.

Where data lives, HTTP contract, edge cases:

```bash
curl -sS -X POST http://127.0.0.1:8000/v1/mute \
  -H 'Content-Type: application/json' \
  -d '{"user_id":"user-1"}'
```

Than we do normal dispatch:

```bash
curl -sS -X POST http://127.0.0.1:8000/v1/dispatch \
  -H 'Content-Type: application/json' \
  -d '{"user_id":"user-1","event_type":"UserSignedUp","payload":{}}'
```

Than finally we unmute user:

```bash
curl -sS -X POST http://127.0.0.1:8000/v1/unmute \
  -H 'Content-Type: application/json' \
  -d '{"user_id":"user-1"}'
```

Edge case muting already muted user tested and it doesn't break code, or give error similarly unmuting user does the same.

Where data live and known limitation:

The list lives in memory and is gone if server is restarted if supposed there is multiple worker there list would not be shared in production server a postgres table would be ideal. to store. this is intentional as I don't want to over complicate exercise in this phase.

## Retry / email failure handling

Persistence schema, response codes, what happens on partial failure (email vs slack):

Schema is persistent it uses SQLite. I will prefer postgres for production (aurora in aws), but I don't want to increase complexity.

The values are mask when we test example. max attempts are 5 for req.

The reason we dont use memory here as compare to mute is because if it email is not recovered.

```bash
curl -sS -X POST http://127.0.0.1:8000/v1/dispatch \
  -H 'Content-Type: application/json' \
  -d '{"user_id":"user-2","event_type":"PleaseFAIL","payload":{}}'
```

To not increase complexity partial_ faliure is setup for email list only if we add word FAIL in json so we get return: status partial failure.

In current code keeping complexity in mind since slack in always passing we only have partial failure in production for emails.

Database will store full email as its secure whereas log have masked email.

## Assumptions and known limitations

Assumption:

- single process. if app is scaled tools like redis can be used for support.
- currently mute list is per worker. so in prod it needs to be in a database
- mute list dont survive restart server but we can easily remove user again
- files like setting.py, pyproject.tomlm and .env.example are unchanged. this is also to provide and demonstrate constraint to AI tools.
- env variable are locked and max retry are 5
- I have picked simplest option and instructed AI tools to do same to have least diff but some places like sqllite working table, route mute api endpoint where added by me
- no background retry worked is used.
- github actions is used for easy testing and to see my edit don't break the code in prod other Devops methodology can be used.
- intentionally comments have been added by AI tool when its initially avoided it on its own this is for me to understand change done by cursor and be transparent about assignment.

*** note both submisson.md and ai-submission.md are written in extremely natural language for transparency they are in now way shape or form reflect actual production documentation standards.

## AI disclosure

Ai disclosure file is attached.

Summary I have used cursor extensively and claude to audit its work.

I first used cursor to analyze entire project using ask mode asking several question back and forth. than ask it to show several approach we can take. I took easy approach as assignment ask for least Diff. than i went to plan mode edit the plan given by cursor than implement it.

I didn't agree with many things cursor initially suggested. and added stuff on my own which it avoided to not make project complex.

Whereas in several area it made project too complex i corrected it to dail down.

I rejected it using generic table but given it proper schema for table.

I added router for mute.py for easily muting and unmuting user for testing.

I also added GitHub action for easy testing.

Further details are in ai-submission.md
