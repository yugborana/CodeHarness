"""Slash commands. Anything typed starting with / lands here."""

import session
from ui import ui

COMMANDS = {
    "/rewind": "jump back to an earlier point in this chat",
    "/sessions": "open a past chat",
}


def preview(message):
    if message.get("tool_calls"):
        return "-> " + message["tool_calls"][0]["function"]["name"]
    return " ".join(str(message.get("content") or "").split())[:70]


def rewind(messages):
    rows = [f"{m['role']:<9} {preview(m)}" for m in messages]
    choice = ui.pick("rewind to", rows)
    if choice is None:
        return messages
    session.rewind_to(choice + 1)
    return messages[: choice + 1]


def sessions(messages):
    saved = session.all_sessions()
    if not saved:
        ui.note("no saved chats yet")
        return messages
    rows = [f"{s['id']}  {s['title']}" for s in saved]
    choice = ui.pick("open chat", rows)
    return messages if choice is None else session.open_session(saved[choice]["id"])


def handle(command, messages):
    if command == "/rewind":
        return rewind(messages)
    if command == "/sessions":
        return sessions(messages)
    ui.note("\n".join(f"{name}  -  {help}" for name, help in COMMANDS.items()))
    return messages