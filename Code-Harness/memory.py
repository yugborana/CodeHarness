"""Project Memory and Instructions (AGENTS.md).

Manages persistent project rules, conventions, architectural notes, and learned
preferences across sessions.
"""

from pathlib import Path

MEMORY_FILENAMES = ["AGENTS.md", ".agents/AGENTS.md", ".agents/memory.md"]
GLOBAL_FILENAMES = [Path.home() / ".agents" / "AGENTS.md", Path.home() / ".agents" / "rules.md"]


def get_memory_path(create: bool = False) -> Path:
    """Find the active project memory path, or the default destination for new memory."""
    for rel in MEMORY_FILENAMES:
        p = Path.cwd() / rel
        if p.is_file():
            return p
    # If not found, default to AGENTS.md in the project root
    return Path.cwd() / "AGENTS.md"


def read_memory() -> str:
    """Read project memory and any global agent rules."""
    parts = []

    # Project-specific memory
    proj_path = get_memory_path()
    if proj_path.is_file():
        text = proj_path.read_text(encoding="utf-8", errors="replace").strip()
        if text:
            parts.append(text)

    # User-global rules (if any exist in ~/.agents/)
    for global_path in GLOBAL_FILENAMES:
        if global_path.is_file():
            global_text = global_path.read_text(encoding="utf-8", errors="replace").strip()
            if global_text:
                parts.append(f"## Global User Rules\n{global_text}")
            break

    return "\n\n".join(parts)


def remember(fact: str) -> str:
    """Append a new learning, convention, or fact to AGENTS.md."""
    fact = fact.strip()
    if not fact:
        return "Error: cannot remember an empty fact."

    path = get_memory_path(create=True)
    clean_fact = fact if fact.startswith("- ") else f"- {fact}"

    if not path.is_file():
        content = (
            "# AGENTS.md\n\n"
            "Project instructions and persistent memory across sessions.\n\n"
            "## Key Learnings & Conventions\n"
            f"{clean_fact}\n"
        )
        path.write_text(content, encoding="utf-8")
        return f"Created {path.name} and remembered: {fact}"

    existing = path.read_text(encoding="utf-8", errors="replace")

    # If already recorded, avoid duplicate lines
    if clean_fact in existing:
        return f"Already remembered in {path.name}."

    # Look for a learnings section to append to, or add one at the end
    if "## Key Learnings & Conventions" in existing:
        parts = existing.split("## Key Learnings & Conventions", 1)
        updated = f"{parts[0]}## Key Learnings & Conventions\n{clean_fact}\n{parts[1].lstrip()}"
    elif "## Project Memory" in existing:
        parts = existing.split("## Project Memory", 1)
        updated = f"{parts[0]}## Project Memory\n{clean_fact}\n{parts[1].lstrip()}"
    else:
        # Append as a new section at the bottom
        prefix = "\n\n" if not existing.endswith("\n\n") else ""
        updated = f"{existing.rstrip()}{prefix}## Key Learnings & Conventions\n{clean_fact}\n"

    path.write_text(updated, encoding="utf-8")
    return f"Remembered in {path.name}: {fact}"


def memory_prompt() -> str:
    """Format the project memory for injection into the system prompt."""
    mem = read_memory()
    if not mem:
        return ""

    return (
        "\n# Project Memory & Instructions (AGENTS.md)\n"
        "The following persistent instructions, rules, and architecture conventions "
        "are defined for this project. Adhere to them strictly:\n"
        f"<project-memory>\n{mem}\n</project-memory>\n"
    )
