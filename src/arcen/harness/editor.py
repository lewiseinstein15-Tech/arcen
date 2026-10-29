"""Offline proposal construction. No candidate is executed or adopted here.

An injected model callback may return a one-file unified diff. Strict parsing,
fixed path allowlists, exact context and prompt validation protect this API from
path traversal and malformed output. This is not yet a campaign, model-provider
integration, patch applier, or substitute for the later policy/adoption gates.
"""

from __future__ import annotations

import json
import re
import tempfile
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from pathlib import Path

from .manifest import MAX_COMPONENT_BYTES
from .model import content_hash
from .resolver import HarnessError, HarnessResolver
from .store import HarnessStore

EDITABLE = frozenset(
    {
        "prompts/system.md",
        "prompts/draft.md",
        "prompts/forge.md",
        "prompts/temper.md",
        "tool-guidance.md",
    }
)
MAX_PATCH_BYTES = 64 * 1024
_HUNK = re.compile(r"@@ -(\d+)(?:,(\d+))? \+(\d+)(?:,(\d+))? @@(?: [^\n]*)?\n\Z")


@dataclass(frozen=True, slots=True)
class Proposal:
    scope: str
    path: str
    diff: str
    before_hash: str
    after: bytes


def apply_exact_diff(original: bytes, path: str, patch: str) -> bytes:
    """Apply a single-file unified diff in memory, with exact context only."""
    if path not in EDITABLE:
        raise HarnessError("component is not editable")
    if type(patch) is not str or len(patch.encode("utf-8")) > MAX_PATCH_BYTES:
        raise HarnessError("invalid or oversized patch")
    try:
        text = original.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise HarnessError("component must be UTF-8") from exc
    if not text.endswith("\n") or "\r" in text or "\r" in patch:
        raise HarnessError("component and patch must use LF with final newlines")
    lines = patch.splitlines(keepends=True)
    if len(lines) < 4 or lines[:2] != [f"--- a/{path}\n", f"+++ b/{path}\n"]:
        raise HarnessError("patch headers must name exactly the editable component")
    source = text.splitlines(keepends=True)
    result: list[str] = []
    old_pos = 0
    index = 2
    changed = False
    hunks = 0
    while index < len(lines):
        match = _HUNK.fullmatch(lines[index])
        if not match:
            raise HarnessError("invalid patch hunk")
        hunks += 1
        old_start, old_count, new_start, new_count = match.groups()
        old_n = int(old_count) if old_count is not None else 1
        new_n = int(new_count) if new_count is not None else 1
        old_at = int(old_start) if old_n == 0 else int(old_start) - 1
        new_at = int(new_start) if new_n == 0 else int(new_start) - 1
        if old_at < old_pos or old_at < 0 or old_at > len(source):
            raise HarnessError("overlapping or out-of-range patch")
        result.extend(source[old_pos:old_at])
        if new_at != len(result):
            raise HarnessError("patch new-line offset mismatch")
        old_pos = old_at
        index += 1
        consumed = produced = 0
        while index < len(lines) and not lines[index].startswith("@@ "):
            line = lines[index]
            if not line.endswith("\n") or not line or line[0] not in " +-":
                raise HarnessError("invalid patch line")
            content = line[1:]
            if line[0] in " -":
                if old_pos >= len(source) or source[old_pos] != content:
                    raise HarnessError("patch context does not match")
                old_pos += 1
                consumed += 1
            if line[0] in " +":
                result.append(content)
                produced += 1
            if line[0] != " ":
                changed = True
            index += 1
        if (consumed, produced) != (old_n, new_n):
            raise HarnessError("patch hunk count mismatch")
    if not hunks or not changed:
        raise HarnessError("empty patch")
    result.extend(source[old_pos:])
    output = "".join(result).encode("utf-8")
    if not output or len(output) > MAX_COMPONENT_BYTES or not output.endswith(b"\n"):
        raise HarnessError("invalid edited component")
    if output == original:
        raise HarnessError("patch makes no change")
    return output


def _validate_prompts(components: Mapping[str, bytes]) -> None:
    """Validate all changed and unchanged prompt sections as a coherent set."""
    with tempfile.TemporaryDirectory(prefix="arcen-proposal-") as directory:
        root = Path(directory)
        for path in EDITABLE:
            target = root / path
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(components[path])
        HarnessResolver(root).resolve()


def propose(
    store: HarnessStore,
    manifest_id: str,
    task: str,
    panel: tuple[Callable[[dict], str], ...],
    *,
    k: int = 1,
) -> tuple[Proposal, ...]:
    """Produce k independent invariant + k domain proposals without writes.

    Each injected callback receives task, scope, component content and permitted
    paths, and must return one JSON object with exactly `path` and `diff`.
    Model calls are explicit and synchronous; no credentials or model routing
    are created by this module. Callers are responsible for budgets and trust.
    """
    if type(task) is not str or not task.strip() or len(task) > 4000:
        raise HarnessError("invalid task")
    if type(k) is not int or not 1 <= k <= 5:
        raise HarnessError("k must be between 1 and 5")
    if (
        type(panel) is not tuple
        or not panel
        or len(panel) > 5
        or not all(callable(x) for x in panel)
    ):
        raise HarnessError("invalid editor panel")
    manifest = store.get_manifest(manifest_id)
    original = {name: store.get_blob(manifest.components[name]) for name in EDITABLE}
    _validate_prompts(original)
    output = []
    for scope in ("invariant", "domain"):
        for index in range(k):
            # Every proposal starts from the same base, never from another
            # candidate. All data passed to callbacks is a fresh copy.
            request = {
                "task": task,
                "scope": scope,
                "index": index,
                "components": {path: original[path].decode("utf-8") for path in sorted(EDITABLE)},
                "instructions": "Return JSON with path and a single-file unified diff using exact a/ and b/ headers. Do not edit any other path.",
            }
            response = panel[index % len(panel)](request)
            if type(response) is not str or len(response.encode("utf-8")) > MAX_PATCH_BYTES + 4096:
                raise HarnessError("invalid editor response")
            try:
                value = json.loads(response, object_pairs_hook=_unique)
            except (json.JSONDecodeError, ValueError) as exc:
                raise HarnessError("invalid editor JSON") from exc
            if type(value) is not dict or set(value) != {"path", "diff"}:
                raise HarnessError("invalid editor response fields")
            path = value["path"]
            if type(path) is not str or path not in EDITABLE:
                raise HarnessError("component is not editable")
            after = apply_exact_diff(original[path], path, value["diff"])
            edited = dict(original)
            edited[path] = after
            _validate_prompts(edited)
            output.append(Proposal(scope, path, value["diff"], content_hash(original[path]), after))
    return tuple(output)


def _unique(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("duplicate JSON key")
        result[key] = value
    return result
