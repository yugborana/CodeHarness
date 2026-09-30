"""The input line.

`input()` cannot edit a line that has wrapped past the screen width - the
terminal owns the wrapping and readline cannot see it. prompt_toolkit redraws
the line itself, so deleting, word jumps and history all keep working once the
text is longer than the screen.

Ctrl+Left/Right for word navigation works natively in prompt_toolkit.
Shift+Enter inserts a newline without submitting.
"""

from pathlib import Path

from prompt_toolkit import PromptSession
from prompt_toolkit.formatted_text import HTML
from prompt_toolkit.history import FileHistory
from prompt_toolkit.key_binding import KeyBindings
from prompt_toolkit.styles import Style

HISTORY = Path.home() / ".agents" / "history"

STYLE = Style.from_dict({"prompt": "bold #9ece6a"})

bindings = KeyBindings()


@bindings.add("escape", "enter")
def _newline(event):
    """Shift-Enter starts a new line instead of sending the message."""
    event.current_buffer.insert_text("\n")


SESSION = None


def read(prompt="> "):
    """Read one message. Raises EOFError on ctrl-d, like input() does."""
    global SESSION
    if SESSION is None:
        HISTORY.parent.mkdir(parents=True, exist_ok=True)
        SESSION = PromptSession(
            history=FileHistory(str(HISTORY)),
            key_bindings=bindings,
            style=STYLE,
        )
    return SESSION.prompt(HTML(f"<prompt>{prompt}</prompt>"))