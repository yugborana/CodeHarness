import argparse
import json

import commands
import session
from context import reminder
from llm import SYSTEM_PROMPT, call_llm
from tools import TOOLS
from ui import ui
from todos import active_form

parser = argparse.ArgumentParser()
parser.add_argument("--resume", action="store_true", help="continue the last session")
parser.add_argument("--debug", action="store_true", help="show the raw model response")
cli = parser.parse_args()

ui.banner()

messages = [{"role": "system", "content": SYSTEM_PROMPT}]
if cli.resume:
    saved = session.all_sessions()
    if saved:
        messages = session.open_session(saved[0]["id"])
        ui.resumed(messages)

while True:
    user_input = ui.ask()
    if not user_input:
        break

    if user_input.startswith("/"):
        messages = commands.handle(user_input, messages)
        session.save(messages)
        continue

    messages.append({"role": "user", "content": user_input})

    while True:
        injection = reminder()
        ui.injection(injection["content"])

        with ui.working(active_form()):
            message, usage = call_llm(messages + [injection])

        messages.append(message.model_dump(exclude_none=True))
        session.save(messages)
        ui.usage(usage)

        if cli.debug:
            ui.debug(message.model_dump(exclude_none=True))

        if message.content:
            ui.agent(message.content)

        if not message.tool_calls:
            break

        for tool_call in message.tool_calls:
            args = json.loads(tool_call.function.arguments)
            result = TOOLS[tool_call.function.name](**args)
            ui.tool(tool_call.function.name, args, result)

            messages.append({
                "role": "tool",
                "tool_call_id": tool_call.id,
                "content": result,
            })
            session.save(messages)

ui.summary()