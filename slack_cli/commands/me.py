"""`slack me` command."""

from __future__ import annotations

import click

from slack_cli.context import AppContext
from slack_cli.normalize import normalize_me
from slack_cli.render import emit_data, render_me


@click.command("me")
@click.pass_obj
def me_command(app: AppContext) -> None:
    """Show authenticated user and workspace information."""

    auth = app.client.auth_test()
    user_payload = {}
    user_id = auth.get("user_id")
    if user_id:
        user_payload = app.client.user_info(user_id)

    item = normalize_me(auth, user_payload, app.settings.workspace)

    if app.output_format == "pretty":
        render_me(app.console, item)
    else:
        emit_data(
            app,
            item,
            default_fields=[
                "workspace",
                "team",
                "team_id",
                "user",
                "user_id",
                "email",
                "tz",
            ],
        )
