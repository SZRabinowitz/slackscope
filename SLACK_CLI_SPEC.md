# Slack CLI Design Spec

## Purpose

Build a read-first CLI bridge to Slack that is optimized for fast terminal reading and composable scripting.

Primary use case:
- quickly list conversations
- read channel/DM history
- inspect threads
- keep output compact and useful

V1 is read-only. Sending messages will be added later.

## Implementation Status

- [x] CLI scaffold implemented (`click` + package layout)
- [x] Slack HTTP client implemented (`httpx`, retries, 429 handling)
- [x] Required env validation implemented (`SLACK_WORKSPACE`, `TOKEN`, `D_COOKIE`)
- [x] Read-only commands implemented: `me`, `users list`, `chat list/show/history/message`, `dm list/history`, `thread show`
- [x] Borderless Rich pretty output implemented (no boxed tables)
- [x] Structured formats implemented: `json`, `jsonl`, `tsv`
- [x] Truncation controls implemented (`--max-text`, `--full-text`)
- [x] Inline reply previews implemented (`--inline-replies`, `--max-inline-threads`)
- [x] Specific-message full read implemented (`slack chat message <chat> <ts>`)
- [x] Chronological day-grouped history view implemented (`Today` / `Yesterday` / date headers)
- [x] Thread reply gutter implemented in history/thread views (`┃ ↳` reply lines)
- [x] Markdown rendering implemented for full-message reads (`chat message` pretty mode)
- [x] Attachment fallback text implemented (`📎 <name> (<type>, <size>)`, including file-only messages)
- [x] List views aligned for readability (fixed metadata columns + spaced preview text)
- [x] Installed entrypoint wired (`uv run slack ...`)
- [ ] Auth commands (`auth login`, `auth status`, `auth logout`) (approved, pending implementation)
- [x] API passthrough commands (`api call`, `api curl`) implemented
- [ ] README command examples and usage guide (pending)
- [ ] Send/reply/reaction features (out of scope for V1)

## Decisions Locked In

- CLI parser: `click`
- HTTP client: `httpx`
- terminal presentation: `rich` (color, emphasis, indentation), no boxed tables by default
- default output style: borderless, compact, human-readable
- machine output available through `--format`

## Auth and Environment

Authentication follows the existing script pattern from `main.py`:

Required env:
- `SLACK_WORKSPACE` (e.g. `flawlessai`)
- `TOKEN` (Slack token)
- `D_COOKIE` (cookie value for `d`)

Env file discovery order for CLI runs:
1. `~/.config/slack/slack.env` (primary)
2. `./slack.env` (local fallback)
3. `./.env` (local fallback)

Optional override:
- `SLACK_ENV_FILE` (explicit dotenv path)

Request shape:
- API base: `https://<workspace>.slack.com/api/<method>`
- include `token` in request params/form body
- include cookie: `d=<D_COOKIE>`

Fail fast on missing required auth/workspace values with concise errors.

## Command Model

Command shape:

```bash
slack <resource> <action> [target] [flags]
```

Resources:
- `me`
- `users`
- `chat`
- `dm`
- `thread`
- `auth` (approved, pending implementation)
- `api`

Target types accepted where relevant:
- `#channel`
- `@user`
- raw IDs: `C...`, `G...`, `D...`, `U...`

## V1 Commands

```bash
slack me
slack users list [--query TEXT] [--limit N]
slack chat list [--type channel|private|dm|mpim|all] [--unread] [--limit N]
slack chat show <chat>
slack chat history <chat> [--limit N] [--since DUR|TS] [--until DUR|TS]
slack chat message <chat> <ts>
slack dm list [--unread] [--limit N]
slack dm history <@user|dm_id> [--limit N] [--since DUR|TS] [--until DUR|TS]
slack thread show <chat> <ts>
```

## Approved Commands (Pending Implementation)

```bash
slack auth login <workspace>
slack auth status
slack auth logout [--yes]
```

### Auth Command Design

`auth login`:
- requires workspace input (`<workspace>`); user input is the source-of-intent workspace
- opens Chrome directly to the requested workspace for interactive Slack sign-in
- captures auth values from browser session:
  - `TOKEN`
  - `D_COOKIE`
- derives observed workspace from browser/API traffic for verification
- if observed workspace does not match requested workspace, abort with a clear mismatch error
- sets `SLACK_WORKSPACE` from the requested workspace after verification
- validates captured values via `auth.test`
- saves validated credentials to `~/.config/slack/slack.env`
- if auto-capture is incomplete, prompts for missing values
- never prints secret values

`auth status`:
- checks credential file presence and required variables
- runs `auth.test` when credentials are available
- reports concise auth/config status without exposing secrets

`auth logout`:
- removes/clears local credential file at `~/.config/slack/slack.env`
- supports non-interactive confirmation via `--yes`

### API Passthrough Design

Implemented commands:

```bash
slack api call <endpoint> [-X METHOD] [-p key=value ...]
slack api curl <endpoint> [--print-command] [--print-only] -- [extra curl args]
```

- `api call` and `api curl` are expert/debug passthrough interfaces.
- Both commands output raw response payloads (no normalization, no pretty schema formatting).
- Global output transforms (`--format`, `--fields`) do not apply to these commands.
- No read/write endpoint gating is applied for `api` commands.

`api call`:
- accepts repeatable params via `-p/--param key=value`
- supports explicit HTTP method via `-X/--method` (default `POST`)

`api curl`:
- wraps auth/base endpoint setup for curl-compatible workflows
- supports optional command preview before execution
  - `--print-command`: print redacted command, then execute
  - `--print-only`: print redacted command, do not execute
- command preview redaction uses full-string find/replace for secrets:
  - token -> `<TOKEN_REDACTED>`
  - cookie `d` -> `<D_COOKIE_REDACTED>`

## Defaults

### `slack chat list` defaults

- `type=all`
- `joined_only=true`
- `archived=false`
- `limit=30`
- sort: unread first, then most recent activity
- include IDs by default for composability

### History defaults (`chat history`, `dm history`)

- oldest-first ordering (chronological; newest at bottom)
- reasonable default limit (for example `30`)
- inline thread reply preview enabled
- message text preview truncation enabled

## Inline Thread Replies in History

When listing message history, thread replies are shown inline for threaded parent messages.

Default behavior:
- `--inline-replies 2`
- `--max-inline-threads 8`

Rules:
- show up to N replies under each parent message
- indent replies under the parent line
- inline preview shows the first N replies in chronological order
- if truncated, show `... +X more`
- full thread is always available via `slack thread show <chat> <ts>`

## Message Text Handling

Long message text is truncated in list-style views and shown in full when requesting a specific message.

Truncation behavior:
- applies to `chat list`, `dm list`, `chat history`, `dm history`, and inline replies in history
- multiline message text is collapsed to a single preview line for list-style output
- append `...` when truncated

Default preview lengths:
- list views default to `--max-text 100`
- history views default to `--max-text 180`

Controls:
- `--max-text N` to set preview length
- `--full-text` to disable truncation for that command

Full message retrieval:
- `slack chat message <chat> <ts>` returns full, untruncated message text with key metadata
- list/history output must include message `ts` and chat identifier so it is easy to pivot into `chat message`

## Output Contract

### Default (`pretty`)

- borderless output
- colorized with Rich (timestamps, actors, metadata emphasis)
- no noisy debug text
- concise and scan-friendly
- text is truncated by default in list-style views according to the truncation policy
- history/thread pretty output is day-grouped with aligned metadata columns and visible reply gutters
- list pretty output uses aligned metadata columns with a wider gap before preview text

### Alternate formats

- `--format pretty` (default)
- `--format json`
- `--format jsonl`
- `--format tsv`

Format text behavior:
- `pretty`: truncated by default in list/history, override with `--full-text`
- `json`/`jsonl`: full text by default for machine readability

### Field selection

- `--fields` supported broadly to control visible/exported columns
- stable key names for machine formats

### Output channels

- stdout: primary command results
- stderr: warnings/errors/diagnostics

## Resolution Rules

Lookup order:

1. raw ID (exact)
2. exact name/handle match
3. normalized name match

On ambiguity:
- show a short list of candidates with IDs
- ask user to rerun with explicit target ID

## Internal Project Structure

```text
slackpresent/
  cli.py
  main.py
  slack_cli/
    __init__.py
    app.py
    config.py
    context.py
    client.py
    errors.py
    resolve.py
    normalize.py
    render.py
    timeparse.py
    commands/
      me.py
      users.py
      chat.py
      dm.py
      thread.py
```

Responsibilities:
- `commands/*`: Click command definitions only
- `client.py`: Slack HTTP methods + retries + pagination helpers
- `normalize.py`: convert Slack payloads to stable records
- `render.py`: pretty/json/jsonl/tsv renderers
- `resolve.py`: `#channel`/`@user`/ID resolution

## API Methods to Use (Read-Only)

- `auth.test`
- `users.list`
- `users.info` (if needed)
- `users.conversations` (joined conversation listing)
- `conversations.list`
- `conversations.info`
- `conversations.history`
- `conversations.replies`
- `conversations.members` (if needed for enrichment)

## Reliability and Errors

- retries for transient `5xx`
- respect `429 Retry-After`
- short friendly errors by default
- optional `--verbose` for technical details
- non-zero exit codes on failures

## Performance Notes

- use cursor-based pagination for list endpoints
- per-run in-memory caches for users/conversations to avoid duplicate lookups
- bounded page/item scans for responsiveness in large workspaces
- conversation snapshot enrichment for reliable unread/latest metadata in list output
- cap reply inlining requests to prevent API explosion

## Future (Out of Scope for V1)

- notifications list support
- send messages (`msg send` / `chat send`)
- reply to thread
- reactions
- file upload/download helpers
- watch/stream mode
