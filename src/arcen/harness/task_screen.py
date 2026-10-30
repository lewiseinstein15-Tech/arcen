"""Conservative task-text screening for a few explicit injection patterns.

This is a heuristic, not a security boundary. It can reject benign security
research and cannot establish that other text is safe. It never logs task text.
"""

from __future__ import annotations

import re
import unicodedata

from .resolver import HarnessError


class SuspiciousTask(HarnessError):
    """A task matched a narrow, predefined injection heuristic."""


_PATTERNS = tuple(
    re.compile(pattern, re.IGNORECASE)
    for pattern in (
        (
            r"\b(?:ignore|disregard|override|forget)\s+(?:(?:all|the|any|your)\s+){0,2}"
            r"(?:previous|prior|above|earlier|system|developer)\s+"
            r"(?:instructions?|directives?|rules?|messages?|prompts?)\b"
        ),
        (
            r"\b(?:reveal|print|exfiltrate|send|leak|disclose)\b.{0,60}"
            r"\b(?:system\s+prompt|developer\s+message|api\s+keys?|credentials?|secrets?)\b"
        ),
        (
            r"\b(?:disable|bypass|ignore|override)\b.{0,40}"
            r"\b(?:guardrails?|sandbox|security\s+policy|safety\s+checks?)\b"
        ),
        (
            r"<\s*/?\s*(?:system|developer)\s*>|<\|im_start\|>\s*(?:system|developer)\b"
            r"|<<\s*/?\s*sys\s*>>|\[/?inst\]"
        ),
    )
)


def screen_task(task: str) -> None:
    """Reject selected explicit role-spoofing and security-bypass phrases.

    Only task text is screened; prompts, repository files, tool outputs and
    model responses remain untrusted and are not screened here. Even task
    attacks are easily reworded or encoded around these simple rules.
    """
    if type(task) is not str or not task.strip() or len(task) > 4000:
        raise HarnessError("invalid task for injection screening")
    text = unicodedata.normalize("NFKC", task)
    text = "".join(char for char in text if unicodedata.category(char) != "Cf")
    text = " ".join(text.split())
    if any(pattern.search(text) for pattern in _PATTERNS):
        raise SuspiciousTask("task matched a prompt-injection heuristic; no task was run")
