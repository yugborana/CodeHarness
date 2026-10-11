"""Lifecycle hooks: run scripts/commands before and after agent turns and tools.

Hooks are defined in  ~/.agents/hooks.yaml  and fire at five points:

  before_agent  — after the user types but before the LLM is called
  after_agent   — after the LLM's final answer (no more tool calls)
  before_tool   — before each individual tool call runs
  after_tool    — after each individual tool call returns
  on_error      — when the agent loop catches an unhandled exception

Each hook entry looks like:

    - name: lint-on-edit
      trigger: after_tool
      command: powershell -c "if ($env:CODEHARNESS_TOOL_NAME -eq 'write_file') { ruff check $env:CODEHARNESS_TOOL_ARGS }"
      timeout_sec: 30
      fail_closed: false       # if true, a failing hook aborts the operation
      enabled: true

Context is passed through environment variables whose names start with
CODEHARNESS_.  Secrets in tool args are redacted before they reach the
hook's environment.
"""

from __future__ import annotations

import json
import logging
import os
import subprocess
from pathlib import Path
from typing import Any

import yaml

from .redaction import redact_tool_args

logger = logging.getLogger(__name__)

HOOKS_FILE = Path.home() / ".agents" / "hooks.yaml"


# ── hook config ───────────────────────────────────────────────────────────

VALID_TRIGGERS = frozenset({
    "before_agent",
    "after_agent",
    "before_tool",
    "after_tool",
    "on_error",
})


def _load_hooks() -> list[dict[str, Any]]:
    """Read ~/.agents/hooks.yaml and return enabled hook dicts."""
    if not HOOKS_FILE.exists():
        return []
    try:
        data = yaml.safe_load(HOOKS_FILE.read_text()) or []
    except Exception as exc:
        logger.warning("Failed to parse %s: %s", HOOKS_FILE, exc)
        return []

    hooks = []
    for entry in data:
        if not isinstance(entry, dict):
            continue
        if not entry.get("enabled", True):
            continue
        trigger = entry.get("trigger", "")
        if trigger not in VALID_TRIGGERS:
            logger.warning("Hook '%s' has invalid trigger '%s', skipping",
                           entry.get("name", "?"), trigger)
            continue
        if not entry.get("command"):
            logger.warning("Hook '%s' has no command, skipping",
                           entry.get("name", "?"))
            continue
        hooks.append(entry)
    return hooks


# ── the hook runner ───────────────────────────────────────────────────────

class HookRunner:
    """Loads hooks once and fires them at the right moments."""

    def __init__(self) -> None:
        self.hooks = _load_hooks()
        if self.hooks:
            names = ", ".join(h["name"] for h in self.hooks)
            logger.info("Loaded %d hook(s): %s", len(self.hooks), names)

    # ── public triggers ───────────────────────────────────────────────

    def before_agent(self, user_message: str) -> None:
        """Called after the user types, before the LLM request."""
        env = self._base_env("before_agent")
        env["CODEHARNESS_USER_MESSAGE"] = user_message
        self._fire("before_agent", env)

    def after_agent(self, user_message: str, agent_response: str) -> None:
        """Called after the LLM's final answer (no pending tool calls)."""
        env = self._base_env("after_agent")
        env["CODEHARNESS_USER_MESSAGE"] = user_message
        env["CODEHARNESS_RESPONSE"] = agent_response[:4000]  # cap for env safety
        self._fire("after_agent", env)

    def before_tool(self, tool_name: str, tool_args: dict[str, Any]) -> None:
        """Called before an individual tool call runs."""
        env = self._base_env("before_tool")
        env["CODEHARNESS_TOOL_NAME"] = tool_name
        safe_args, _ = redact_tool_args(tool_args)
        env["CODEHARNESS_TOOL_ARGS"] = json.dumps(safe_args, default=str)
        self._fire("before_tool", env)

    def after_tool(
        self,
        tool_name: str,
        tool_args: dict[str, Any],
        tool_result: str,
    ) -> None:
        """Called after an individual tool call returns."""
        env = self._base_env("after_tool")
        env["CODEHARNESS_TOOL_NAME"] = tool_name
        safe_args, _ = redact_tool_args(tool_args)
        env["CODEHARNESS_TOOL_ARGS"] = json.dumps(safe_args, default=str)
        env["CODEHARNESS_TOOL_RESULT"] = tool_result[:4000]
        self._fire("after_tool", env)

    def on_error(self, error: Exception) -> None:
        """Called when the agent loop catches an unhandled exception."""
        env = self._base_env("on_error")
        env["CODEHARNESS_ERROR"] = f"{type(error).__name__}: {error}"
        self._fire("on_error", env)

    # ── internals ─────────────────────────────────────────────────────

    def _base_env(self, trigger: str) -> dict[str, str]:
        env = os.environ.copy()
        env["CODEHARNESS_TRIGGER"] = trigger
        env["CODEHARNESS_CWD"] = str(Path.cwd())
        return env

    def _fire(self, trigger: str, env: dict[str, str]) -> None:
        for hook in self.hooks:
            if hook["trigger"] != trigger:
                continue
            try:
                self._run(hook, env)
            except Exception as exc:
                logger.warning("Hook '%s' failed: %s", hook.get("name", "?"), exc)
                if hook.get("fail_closed", False):
                    raise

    def _run(self, hook: dict[str, Any], env: dict[str, str]) -> None:
        timeout = hook.get("timeout_sec", 30)
        try:
            subprocess.run(
                hook["command"],
                shell=True,
                cwd=str(Path.cwd()),
                env=env,
                timeout=timeout,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
            )
        except subprocess.TimeoutExpired:
            logger.warning(
                "Hook '%s' timed out after %ds", hook.get("name", "?"), timeout
            )


# ── module-level singleton so it can be imported easily ───────────────────

hooks = HookRunner()