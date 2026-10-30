"""Resolve the four file-based prompt components into an immutable snapshot.

The bundled files are the only production default. A caller may explicitly
resolve a trusted harness directory; this does not implement or select refs.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from string import Formatter
from typing import Any

MAX_PROMPT_BYTES = 128 * 1024
SECTIONS = {
    "draft": frozenset(
        {
            "job",
            "classify",
            "strict",
            "direct",
            "goal-template",
            "failed-step-template",
        }
    ),
    "tool-guidance": frozenset({"plan", "research"}),
    "forge": frozenset({"job"}),
    "temper": frozenset({"job"}),
}
_HEADING = re.compile(r"^## ([a-z][a-z0-9-]*)\n", re.MULTILINE)


class HarnessError(ValueError):
    """Required prompt data is missing or malformed; no fallback is used."""


@dataclass(frozen=True, slots=True)
class ResolvedPrompts:
    identity_template: str
    planner_job: str
    executor_job: str
    verifier_job: str
    classify: str
    plan: str
    research: str
    strict: str
    direct: str
    goal_template: str
    failed_step_template: str


def _read_utf8(item: Any, name: str) -> str:
    try:
        with item.open("rb") as stream:
            raw = stream.read(MAX_PROMPT_BYTES + 1)
    except OSError as exc:
        raise HarnessError(f"cannot read prompt {name}") from exc
    return _decode_utf8(raw, name)


def _decode_utf8(raw: bytes, name: str) -> str:
    if len(raw) > MAX_PROMPT_BYTES:
        raise HarnessError(f"prompt {name} exceeds {MAX_PROMPT_BYTES} bytes")
    try:
        text = raw.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise HarnessError(f"prompt {name} is not UTF-8") from exc
    if not text or "\r" in text or not text.endswith("\n"):
        raise HarnessError(f"prompt {name} must be nonempty LF-terminated UTF-8")
    return text


def _sections(text: str, component: str) -> dict[str, str]:
    matches = list(_HEADING.finditer(text))
    if not matches or matches[0].start() != 0:
        raise HarnessError(f"prompt {component} must begin with a section heading")
    found: dict[str, str] = {}
    for i, match in enumerate(matches):
        name = match.group(1)
        if name in found:
            raise HarnessError(f"duplicate section {name} in {component}")
        end = matches[i + 1].start() if i + 1 < len(matches) else len(text)
        # Strip exactly the file-format separator, not prompt whitespace.
        value = text[match.end() : end].removesuffix("\n")
        if not value.strip():
            raise HarnessError(f"empty section {name} in {component}")
        found[name] = value
    if set(found) != SECTIONS[component]:
        raise HarnessError(f"invalid sections in {component}: {sorted(found)}")
    return found


def _template(text: str, fields: set[str], name: str) -> None:
    try:
        parsed = list(Formatter().parse(text))
    except ValueError as exc:
        raise HarnessError(f"invalid template {name}") from exc
    actual = {field for _, field, _, _ in parsed if field is not None}
    if actual != fields or any(fmt or conv for _, field, fmt, conv in parsed if field is not None):
        raise HarnessError(f"template {name} must use only {sorted(fields)}")


class HarnessResolver:
    """Read bundled prompts, or `<trusted_root>/prompts/*.md` when explicit."""

    def __init__(self, root: str | Path | None = None) -> None:
        self.root = Path(root).expanduser() if root is not None else None

    def resolve(self) -> ResolvedPrompts:
        if self.root is None:
            return default_prompts()
        directory = self.root / "prompts"
        if directory.is_symlink():
            raise HarnessError("prompt directory cannot be a symlink")
        raw: dict[str, str] = {}
        for component in ("system", "draft", "forge", "temper"):
            item = directory.joinpath(f"{component}.md")
            if isinstance(item, Path) and item.is_symlink():
                raise HarnessError(f"prompt {component} cannot be a symlink")
            raw[component] = _read_utf8(item, component)
        guidance_file = self.root / "tool-guidance.md"
        if isinstance(guidance_file, Path) and guidance_file.is_symlink():
            raise HarnessError("tool guidance cannot be a symlink")
        return _resolve_text(raw, _read_utf8(guidance_file, "tool-guidance"))


def _resolve_text(raw: dict[str, str], guidance_text: str) -> ResolvedPrompts:
    guidance = _sections(guidance_text, "tool-guidance")
    identity = raw["system"].removesuffix("\n")
    if not identity.strip():
        raise HarnessError("system prompt cannot be empty")
    draft = _sections(raw["draft"], "draft")
    forge = _sections(raw["forge"], "forge")
    temper = _sections(raw["temper"], "temper")
    _template(identity, {"agent", "job"}, "system")
    _template(draft["goal-template"], {"goal"}, "draft goal")
    _template(draft["failed-step-template"], {"step"}, "draft failed step")
    return ResolvedPrompts(
        identity_template=identity,
        planner_job=draft["job"],
        executor_job=forge["job"],
        verifier_job=temper["job"],
        classify=draft["classify"],
        plan=guidance["plan"],
        research=guidance["research"],
        strict=draft["strict"],
        direct=draft["direct"],
        goal_template=draft["goal-template"],
        failed_step_template=draft["failed-step-template"],
    )


@lru_cache(maxsize=1)
def default_prompts() -> ResolvedPrompts:
    """One immutable packaged snapshot per process; restart to pick up edits."""
    from .manifest import default_bundle

    blobs = default_bundle().components
    raw = {
        name: _decode_utf8(blobs[f"prompts/{name}.md"], name)
        for name in ("system", "draft", "forge", "temper")
    }
    return _resolve_text(raw, _decode_utf8(blobs["tool-guidance.md"], "tool-guidance"))
