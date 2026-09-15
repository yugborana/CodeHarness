"""Late injection: a small block appended just before we send.

It goes at the END of the message list so the stable prefix in front of it
stays cached.
"""

import os
import subprocess
from datetime import datetime

SEEN = {}

def note_read(path):
    SEEN[path] = os.path.getmtime(path)


def stale_files():
    return [p for p, mtime in SEEN.items() if os.path.getmtime(p) != mtime]

def git_branch():
    result = subprocess.run(
        "git branch --show-current", shell=True, capture_output=True, text=True
    )
    return result.stdout.strip() or "(detached)"


def reminder():
    """The block we append to the messages on every turn."""
    return {
        "role": "user",
        "content": (
            "<env>\n"
            f"time: {datetime.now():%Y-%m-%d %H:%M}\n"
            f"git branch: {git_branch()}\n"
            "</env>" + stale_note()
        ),
    }


def stale_note():
    """Warn about files that changed on disk since the agent read them."""
    changed = stale_files()
    if not changed:
        return ""
    return (
        "\n<system-reminder>\n"
        "These files changed on disk since you read them. Read them again "
        "before editing:\n" + "\n".join(changed) + "\n</system-reminder>"
    )