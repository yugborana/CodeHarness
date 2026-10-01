import json
import os

from openai import OpenAI

from . import config
from .skills import skills_prompt
from .tools import TOOLS, TOOL_SCHEMAS

client = OpenAI(
    base_url=config.BASE_URL,
    api_key=config.API_KEY,
)

SYSTEM_PROMPT = f"""
You are a coding agent. Your job is to code. Always code.
Use the powershell tool to inspect files.
Use write_file to create files and str_replace to edit them.
Use web_search to look up documentation, error messages, or APIs you are unsure about.
Answer back to the user once exploration is done.

For any task that takes more than one step, call write_todos first and plan it
out. Send the whole list every time you call it - it replaces the old one.
Keep exactly one task in_progress, mark it done the moment it is finished, and
move the next one to in_progress in the same call. Do not batch up completions
at the end. Skip the tool entirely for single-step tasks; it is noise there.

Do NOT repeat tool outputs, file contents, or diffs back to the user in your response. The user can already see them directly in their terminal.

The current list is injected back to you every turn inside <todos> tags, so
that block - not the transcript - is the truth about where you are.

When you need to understand how something works - where a feature lives, how
data flows, what calls what - send a task subagent instead of grepping your
way there yourself. It explores in its own context window and hands you back
just the findings, so the search does not fill yours. It cannot see this
conversation, so write the question so it stands alone. Do all editing
yourself; the subagent only reads.

Long tool output is cut short, and the whole thing is written to a temp file
whose path is given at the cut. Page through it with Select-Object -First/Last,
Select-String, or Get-Content rather than asking for it again. That file only
exists for the current turn, so read it now or re-run the command later.

Your current working directory is: {os.getcwd()}

You have skills available. Each one is a set of instructions for a task.
If a skill matches what the user wants, call read_skill first and follow it.

{skills_prompt()}
"""


def _extract_usage(usage):
    """Pull the fields we track out of an API usage object."""
    completion_details = getattr(usage, "completion_tokens_details", None)
    prompt_details = getattr(usage, "prompt_tokens_details", None)
    return {
        "prompt_tokens": getattr(usage, "prompt_tokens", 0),
        "completion_tokens": getattr(usage, "completion_tokens", 0),
        "reasoning_tokens": getattr(completion_details, "reasoning_tokens", None),
        "cached_tokens": getattr(prompt_details, "cached_tokens", None),
    }


def call_llm(messages, tools=None, on_token=None):
    """Call the LLM and return (message, usage).

    on_token(str)  — if provided, content is streamed token by token through
                     this callback as it arrives.  The returned message is
                     identical either way; streaming only changes *when* you
                     see the text, not *what* you get back.
    """
    if on_token is None:
        # Non-streaming path (compact, subagent)
        response = client.chat.completions.create(
            model=config.MODEL,
            messages=messages,
            tools=tools or TOOL_SCHEMAS,
        )
        return response.choices[0].message, _extract_usage(response.usage)

    # ---- streaming path ------------------------------------------------
    try:
        stream = client.chat.completions.create(
            model=config.MODEL,
            messages=messages,
            tools=tools or TOOL_SCHEMAS,
            stream=True,
            stream_options={"include_usage": True},
        )
    except Exception:
        # Provider doesn't support streaming or stream_options — fall back
        response = client.chat.completions.create(
            model=config.MODEL,
            messages=messages,
            tools=tools or TOOL_SCHEMAS,
        )
        message = response.choices[0].message
        if message.content:
            on_token(message.content)
        return message, _extract_usage(response.usage)

    content_parts = []
    tool_calls = {}          # index -> {id, type, function: {name, arguments}}
    usage_data = None

    for chunk in stream:
        if getattr(chunk, "usage", None):
            usage_data = chunk.usage

        if not chunk.choices:
            continue

        delta = chunk.choices[0].delta

        # Stream content tokens live
        if delta.content:
            content_parts.append(delta.content)
            on_token(delta.content)

        # Accumulate tool call deltas (they arrive in pieces)
        if delta.tool_calls:
            for tc in delta.tool_calls:
                idx = tc.index
                if idx not in tool_calls:
                    tool_calls[idx] = {
                        "id": "", "type": "function",
                        "function": {"name": "", "arguments": ""},
                    }
                entry = tool_calls[idx]
                if tc.id:
                    entry["id"] = tc.id
                if tc.function:
                    if tc.function.name:
                        entry["function"]["name"] = tc.function.name
                    if tc.function.arguments:
                        entry["function"]["arguments"] += tc.function.arguments

    # Reconstruct the same message type the non-streaming path returns
    from openai.types.chat import ChatCompletionMessage
    from openai.types.chat.chat_completion_message_tool_call import (
        ChatCompletionMessageToolCall, Function,
    )

    final_tool_calls = None
    if tool_calls:
        final_tool_calls = [
            ChatCompletionMessageToolCall(
                id=tool_calls[i]["id"],
                type="function",
                function=Function(
                    name=tool_calls[i]["function"]["name"],
                    arguments=tool_calls[i]["function"]["arguments"],
                ),
            )
            for i in sorted(tool_calls)
        ]

    message = ChatCompletionMessage(
        role="assistant",
        content="".join(content_parts) or None,
        tool_calls=final_tool_calls,
    )

    usage = _extract_usage(usage_data) if usage_data else {
        "prompt_tokens": 0, "completion_tokens": 0,
        "reasoning_tokens": None, "cached_tokens": None,
    }

    return message, usage


if __name__ == "__main__":
    user_input = input("Enter your prompt> ")

    message, usage = call_llm([
        {"role": "system", "content": SYSTEM_PROMPT},
        {"role": "user", "content": user_input},
    ])

    print("\nAgent: ", message.content, "\n")

    if message.tool_calls:
        tool_call = message.tool_calls[0]
        args = json.loads(tool_call.function.arguments)
        result = TOOLS[tool_call.function.name](**args)
        print("Tool: ", tool_call.function.name, args)
        print(result, "\n")

    print(usage)