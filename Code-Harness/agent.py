import argparse

from . import commands
from . import compact
from . import git_snap
from . import history
from . import session
from .context import reminder
from .llm import SYSTEM_PROMPT, call_llm
from . import sandbox
from .todos import active_form
from .tools import execute
from .ui import ui


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--resume", action="store_true", help="continue the last session")
    parser.add_argument("--debug", action="store_true", help="show the raw model response")
    cli = parser.parse_args()

    ui.banner(sandbox.name())

    messages = [{"role": "system", "content": SYSTEM_PROMPT}]
    if cli.resume:
        saved = session.all_sessions()
        if saved:
            messages = session.open_session(saved[0]["id"])
            history.strip(messages)
            ui.resumed(messages)
            ui.replay(messages)

    while True:
        user_input = ui.ask()
        if not user_input:
            break

        if user_input.startswith("/"):
            messages = commands.handle(user_input, messages)
            session.save(messages)
            continue

        messages.append({"role": "user", "content": user_input})
        git_snap.new_turn()

        while True:
            injection = reminder()
            ui.injection(injection["content"])

            if history.fit(messages):
                ui.note("dropped old tool output to make this request fit")

            streamed = False
            spinner = ui.spinner_start(active_form())

            def on_token(token):
                nonlocal streamed
                if not streamed:
                    spinner.stop()
                    ui.stream_start()
                    streamed = True
                ui.stream_token(token)

            try:
                message, usage = call_llm(messages + [injection], on_token=on_token)
            finally:
                if streamed:
                    ui.stream_end()
                else:
                    spinner.stop()

            messages.append(message.model_dump(exclude_none=True))
            session.save(messages)
            ui.usage(usage)

            if cli.debug:
                ui.debug(message.model_dump(exclude_none=True))

            if not message.tool_calls:
                break

            for tool_call in message.tool_calls:
                args, result = execute(tool_call)
                ui.tool(tool_call.function.name, args, result)

                messages.append({
                    "role": "tool",
                    "tool_call_id": tool_call.id,
                    "content": result,
                })
                session.save(messages)

        history.sweep()   # the turn is over: bin its temp files
        history.strip(messages)  # ...and shrink the tool output it produced

        if compact.needed(usage):
            messages = commands.compact(messages)

    ui.summary()


if __name__ == "__main__":
    main()