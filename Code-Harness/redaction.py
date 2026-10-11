"""Secret redaction for tool output, arguments, and session logs.

Scans text for known secret patterns (API keys, tokens, private keys, JWTs)
and replaces them with safe placeholders.  This keeps secrets out of the
conversation transcript, the session file, and any hook environment variables.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any


@dataclass
class RedactionReport:
    """Tracks how many secrets of each kind were redacted."""

    count: int = 0
    kinds: dict[str, int] = field(default_factory=dict)

    def add(self, kind: str) -> None:
        self.count += 1
        self.kinds[kind] = self.kinds.get(kind, 0) + 1

    def merge(self, other: "RedactionReport") -> None:
        self.count += other.count
        for kind, count in other.kinds.items():
            self.kinds[kind] = self.kinds.get(kind, 0) + count

    def summary(self) -> str:
        """One-line summary for UI display, empty if nothing was redacted."""
        if not self.count:
            return ""
        parts = ", ".join(f"{k}: {v}" for k, v in sorted(self.kinds.items()))
        return f"[redacted {self.count} secret(s): {parts}]"


@dataclass(frozen=True)
class SecretPattern:
    kind: str
    regex: re.Pattern[str]
    placeholder: str
    preserve_prefix: bool = False


# ── patterns, ordered from most specific to most generic ──────────────────

SECRET_PATTERNS: tuple[SecretPattern, ...] = (
    SecretPattern(
        kind="private_key",
        regex=re.compile(
            r"-----BEGIN [A-Z ]*PRIVATE KEY-----.*?-----END [A-Z ]*PRIVATE KEY-----",
            re.DOTALL,
        ),
        placeholder="[REDACTED:PRIVATE_KEY]",
    ),
    SecretPattern(
        kind="openrouter_api_key",
        regex=re.compile(r"\bsk-or-v1-[A-Za-z0-9_-]{16,}\b"),
        placeholder="[REDACTED:OPENROUTER_API_KEY]",
    ),
    SecretPattern(
        kind="anthropic_api_key",
        regex=re.compile(r"\bsk-ant-[A-Za-z0-9_-]{16,}\b"),
        placeholder="[REDACTED:ANTHROPIC_API_KEY]",
    ),
    SecretPattern(
        kind="openai_api_key",
        regex=re.compile(r"\bsk-[A-Za-z0-9_-]{20,}\b"),
        placeholder="[REDACTED:OPENAI_API_KEY]",
    ),
    SecretPattern(
        kind="github_token",
        regex=re.compile(r"\bgh[pousr]_[A-Za-z0-9_]{20,}\b"),
        placeholder="[REDACTED:GITHUB_TOKEN]",
    ),
    SecretPattern(
        kind="jwt",
        regex=re.compile(
            r"\beyJ[A-Za-z0-9_-]{8,}\.[A-Za-z0-9_-]{8,}\.[A-Za-z0-9_-]{8,}\b"
        ),
        placeholder="[REDACTED:JWT]",
    ),
    SecretPattern(
        kind="generic_secret_assignment",
        regex=re.compile(
            r"(?P<prefix>\b[A-Z0-9_]*(?:API[_-]?KEY|TOKEN|SECRET|PASSWORD|AUTHORIZATION)[A-Z0-9_]*\b\s*[:=]\s*[\"']?)(?P<secret>(?!\[REDACTED:)[^\s\"']{8,})",
            re.IGNORECASE,
        ),
        placeholder="[REDACTED:SECRET]",
        preserve_prefix=True,
    ),
)


# ── public API ────────────────────────────────────────────────────────────

def redact_text(text: str) -> tuple[str, RedactionReport]:
    """Scan a string and replace every matched secret with a placeholder."""
    report = RedactionReport()
    redacted = text
    for pattern in SECRET_PATTERNS:
        redacted = _replace_pattern(redacted, pattern, report)
    return redacted, report


def redact_value(value: Any) -> tuple[Any, RedactionReport]:
    """Recursively redact secrets inside strings, dicts, lists and tuples."""
    if isinstance(value, str):
        return redact_text(value)

    if isinstance(value, dict):
        report = RedactionReport()
        out: dict[Any, Any] = {}
        for k, v in value.items():
            rv, rr = redact_value(v)
            report.merge(rr)
            out[k] = rv
        return out, report

    if isinstance(value, (list, tuple)):
        report = RedactionReport()
        items = []
        for item in value:
            rv, rr = redact_value(item)
            report.merge(rr)
            items.append(rv)
        return type(value)(items), report

    return value, RedactionReport()


def redact_tool_args(args: dict[str, Any]) -> tuple[dict[str, Any], RedactionReport]:
    """Redact secrets in a tool call's arguments dict."""
    return redact_value(args)


def redact_tool_result(result: str) -> tuple[str, RedactionReport]:
    """Redact secrets in the string result a tool returns."""
    return redact_text(result)


# ── internals ─────────────────────────────────────────────────────────────

def _replace_pattern(text: str, pattern: SecretPattern, report: RedactionReport) -> str:
    def replace(match: re.Match[str]) -> str:
        report.add(pattern.kind)
        if pattern.preserve_prefix:
            return f"{match.group('prefix')}{pattern.placeholder}"
        return pattern.placeholder

    return pattern.regex.sub(replace, text)