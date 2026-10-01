"""Git snapshots for undo.
Before the agent's first file write in a turn, we snapshot the entire working
tree (including untracked files) using git stash. This gives us a restore point
that `/undo` can pop back to.
Flow:
  1. User sends a message                     -> new_turn()
  2. Agent calls write_file or str_replace     -> snapshot() (only first time)
  3. Agent makes its changes
  4. User types /undo                          -> undo()
     -> working tree reverts to step 2
Uses `git stash create` + `git stash store` so the working tree is never
modified during snapshotting — zero disruption.
"""

import subprocess
from pathlib import Path

_project = Path.cwd().resolve()
_snapped_this_turn = False
_turn = 0
LABEL_PREFIX = "codeharness"


def _git(*args):
    """Run a git command in the project directory. Returns CompletedProcess."""
    return subprocess.run(
        ["git", *args],
        capture_output=True,
        text=True,
        cwd=str(_project),
    )


def _is_repo():
    """Is the project directory inside a git repo?"""
    return _git("rev-parse", "--git-dir").returncode == 0


# ------------------------------------------------------------------- turns
def new_turn():
    """Mark the start of a new user turn. Resets the per-turn snapshot flag."""
    global _snapped_this_turn, _turn
    _snapped_this_turn = False
    _turn += 1


# ---------------------------------------------------------------- snapshot
def snapshot():
    """Take a snapshot if we haven't already this turn.

    Called by write_file / str_replace before they write. Only the first
    call per turn actually creates a stash entry; the rest are no-ops.

    Uses git plumbing so the working tree and index are never touched:
      - `git stash create` builds a merge commit of index+worktree
      - `git stash store` files it in the stash reflog with our label
    """
    global _snapped_this_turn

    if _snapped_this_turn:
        return

    if not _is_repo():
        _snapped_this_turn = True  # don't retry every tool call
        return

    label = f"{LABEL_PREFIX}:turn-{_turn}"

    # stash push handles untracked files, but modifies the working tree.
    # So if it succeeds in creating a stash, we instantly apply it back.
    before = _git("stash", "list").stdout
    _git("stash", "push", "--include-untracked", "-m", label)
    after = _git("stash", "list").stdout

    if before != after:
        # A stash was created! Apply it back to restore the working tree
        # exactly as it was, including the index.
        _git("stash", "apply", "--index", "stash@{0}")

    _snapped_this_turn = True


# ------------------------------------------------------------------- undo
def _list():
    """All our stash entries, most recent first."""
    result = _git("stash", "list")
    entries = []

    for line in result.stdout.splitlines():
        if f"{LABEL_PREFIX}:" not in line:
            continue

        # Format:
        # "stash@{N}: On branch: codeharness:turn-M"
        index = line.split(":")[0].strip()
        after = line.split(f"{LABEL_PREFIX}:")[1]
        turn_str = after.strip().rstrip("}")

        try:
            turn_num = int(turn_str.replace("turn-", ""))
        except ValueError:
            continue

        entries.append({"index": index, "turn": turn_num})

    return entries


def undo(turn=None):
    """Revert the working tree to the snapshot before a turn.

    If turn is None, uses the most recent snapshot.

    Returns a human-readable status message.
    """
    if not _is_repo():
        return "Not in a git repository — nothing to undo."

    entries = _list()

    if not entries:
        return "No snapshots available. The agent hasn't written any files yet."

    if turn is not None:
        target = next((e for e in entries if e["turn"] == turn), None)

        if not target:
            avail = ", ".join(str(e["turn"]) for e in entries)
            return f"No snapshot for turn {turn}. Available turns: {avail}"
    else:
        target = entries[0]

    # 1. Discard everything the agent did.
    _git("checkout", "--", ".")
    _git("clean", "-fd")

    # 2. Restore the snapshot.
    result = _git("stash", "apply", target["index"])

    if result.returncode != 0:
        return f"Undo failed: {result.stderr.strip()}"

    # 3. Drop the stash entry so it doesn't pile up.
    _git("stash", "drop", target["index"])

    return f"Reverted to the state before turn {target['turn']}."
