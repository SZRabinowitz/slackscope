# AGENTS.md

## Project Intent

A Python CLI (`slack`) wrapping the Slack Web API to list channels/DMs and read message history and threads, designed for both human and AI agent use.

- Keep workflows fast, clear, and practical for listing and reading Slack content.

## Architecture Map

- `slack_cli/app.py` (CLI entry)
- `slack_cli/client.py` (Slack API layer)
- `slack_cli/commands/*` (command groups)
- `slack_cli/render.py` (output rendering)
- `slack_cli/normalize.py` (message shaping, attachment fallback)

## First Steps For Any Agent

1. Do a deep dive into the entire codebase and understand all code before proposing or making changes.
2. Read `SLACK_CLI_SPEC.md` fully before any design or implementation work.

## Command Execution Note

- Use `uv run ...` when executing Python or Slack CLI commands in this repo.
- Add dependencies with `uv add <package>` from the repo root (do not edit dependency lists manually).
- Examples: `uv run python -m py_compile ...`, `uv run slack chat list --limit 1`.

## Workflow Rules

- Spec first, then implementation.
- When the user requests a feature:
  1. Design it first.
  2. Present the design and ask for approval.
  3. After approval, ask permission before updating any markdown files.
  4. Add approved design updates to `SLACK_CLI_SPEC.md` only after permission.
  5. Wait for explicit instruction to implement before coding.
- If the agent thinks it is a good time to commit, ask the user first.
- Never update any markdown files (`*.md`) without explicit user permission.

## Post-Change Checklist

After code changes, decide whether these source-of-truth files should be updated:

1. `SLACK_CLI_SPEC.md` (status updates or behavior changes)
2. `skills/slack-cli-read/SKILL.md`
3. `AGENTS.md`

## Testing Checklist

- Run syntax check:
  - `uv run python -m py_compile cli.py slack_cli/*.py slack_cli/commands/*.py`
- Run targeted smoke checks for changed behavior:
  - `uv run slack chat list --limit 1`
  - `uv run slack dm history <target> --limit 5`
  - `uv run slack thread show <chat_or_dm> <thread_ts>`
