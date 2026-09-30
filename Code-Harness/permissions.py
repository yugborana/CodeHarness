"""Which tool calls need a human.

The sandbox decides what is *possible*. These rules only decide what is worth
interrupting you for - so read-only commands run silently, and the risky ones
still stop and ask.
"""

import re
from fnmatch import fnmatch
from pathlib import Path

PROJECT = Path.cwd().resolve()

POWERSHELL_RULES = {
    "*": "ask",
    # read-only: let them through
    "Get-ChildItem*": "allow",
    "Get-Location": "allow",
    "Set-Location *": "allow",
    "Write-Output *": "allow",
    "Sort-Object*": "allow",
    "Select-Object -Unique*": "allow",
    "Select-Object *": "allow",
    "Split-Path -Leaf*": "allow",
    "Split-Path -Parent*": "allow",
    "Get-Date*": "allow",
    "Get-ChildItem Env:*": "allow",
    "Get-Content *": "allow",
    "Select-Object -First*": "allow",
    "Select-Object -Last*": "allow",
    "Get-Content * | Measure-Object*": "allow",
    "Get-Item *": "allow",
    "Get-Command *": "allow",
    "Select-String *": "allow",
    "rg *": "allow",
    "Get-ChildItem * -Recurse*": "allow",
    "tree*": "allow",
    "git status*": "allow",
    "git diff*": "allow",
    "git log*": "allow",
    "git show*": "allow",
    "git ls-files*": "allow",
    "pytest*": "allow",
    "python -m pytest*": "allow",

    # risky: never, even if the user says yes
    "Remove-Item *": "deny",
    "sudo *": "deny",
    "Set-Acl *": "deny",
    "takeown *": "deny",
    "Invoke-WebRequest *": "deny",
    "curl *": "deny",
    "wget *": "deny",
    "git push*": "deny",
    "git reset*": "deny",
    "git clean*": "deny",
}

SEPARATORS = re.compile(r"&&|\|\||;|\|")


def decide(command):
    """Rate every part of a compound command; the strictest verdict wins."""
    verdicts = []
    for part in SEPARATORS.split(command):
        action = "ask"
        for pattern, rule in POWERSHELL_RULES.items():
            if fnmatch(part.strip(), pattern):
                action = rule
        verdicts.append(action)

    for strictest in ("deny", "ask"):
        if strictest in verdicts:
            return strictest
    return "allow"


def inside_project(path):
    return PROJECT in Path(path).resolve().parents


def check(name, args):
    """Return (action, reason). Action is allow, ask or deny."""
    if name == "powershell":
        return decide(args["command"]), f"run: {args['command']}"

    if name in ("write_file", "str_replace") and not inside_project(args["path"]):
        return "ask", f"{name} outside {PROJECT}: {args['path']}"

    return "allow", None