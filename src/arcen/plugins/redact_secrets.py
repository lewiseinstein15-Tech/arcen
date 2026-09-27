"""The shipped redact-secrets plugin (BACKEND-SPEC Part 8, rule 4).

Defence-in-depth: scrubs value-shaped secret patterns (sk-…, ghp_…,
Bearer …) from tool results before they reach the stream or the session
file. Config references secrets by $VAR; this plugin catches anything
that leaks through tool output.
"""

import re

from arcen.plugins.loader import Plugin, hook

PATTERNS = [
    re.compile(r"sk-[A-Za-z0-9_-]{8,}"),
    re.compile(r"ghp_[A-Za-z0-9]{20,}"),
    re.compile(r"github_pat_[A-Za-z0-9_]{20,}"),
    re.compile(r"Bearer\s+[A-Za-z0-9._-]{16,}"),
    re.compile(r"xox[baprs]-[A-Za-z0-9-]{10,}"),
]

REDACTED = "[REDACTED]"


def redact_text(text: str) -> str:
    out = text
    for pattern in PATTERNS:
        out = pattern.sub(REDACTED, out)
    return out


class RedactSecrets(Plugin):
    name = "redact-secrets"

    @hook("after_tool")
    def scrub(self, event: dict) -> dict:
        if event.get("tool") in {"bash", "file.read", "http.get", "http.post"} or "result" in event:
            result = event.get("result")
            if isinstance(result, dict):
                for key, value in list(result.items()):
                    if isinstance(value, str):
                        result[key] = redact_text(value)
            elif isinstance(result, str):
                event["result"] = redact_text(result)
        return event
