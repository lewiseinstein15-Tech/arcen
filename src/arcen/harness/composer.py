"""Compose validated editor proposals without executing or adopting them.

Conflicts are reported rather than guessed. This is an offline H-12 foundation,
not a campaign, a behavioral evaluation, or authorization to change a ref.
"""

from __future__ import annotations

from dataclasses import dataclass
from types import MappingProxyType

from .editor import _HUNK, EDITABLE, Proposal, _validate_prompts, apply_exact_diff
from .manifest import Manifest, default_manifest
from .model import content_hash
from .policy import TIER_0
from .resolver import HarnessError
from .store import HarnessStore

MAX_PROPOSALS = 10


@dataclass(frozen=True, slots=True)
class Conflict:
    path: str
    first: int
    second: int


@dataclass(frozen=True, slots=True)
class Composition:
    baseline_id: str
    candidate_id: str | None
    changed_paths: tuple[str, ...]
    conflicts: tuple[Conflict, ...]


@dataclass(frozen=True, slots=True)
class _Edit:
    start: int
    end: int
    replacement: tuple[str, ...]


def _edits(original: bytes, path: str, patch: str, after: bytes) -> tuple[_Edit, ...]:
    """Derive exact base-line edits only after strict unified-diff validation."""
    lines = patch.splitlines(keepends=True)
    edits: list[_Edit] = []
    cursor = 0
    pending: int | None = None
    replacement: list[str] = []

    def flush() -> None:
        nonlocal pending, replacement
        if pending is not None:
            edits.append(_Edit(pending, cursor, tuple(replacement)))
            pending = None
            replacement = []

    for line in lines[2:]:
        match = _HUNK.fullmatch(line)
        if match:
            flush()
            start, count, _, _ = match.groups()
            cursor = int(start) if count == "0" else int(start) - 1
        elif line[0] == " ":
            flush()
            cursor += 1
        elif line[0] == "-":
            if pending is None:
                pending = cursor
            cursor += 1
        elif line[0] == "+":
            if pending is None:
                pending = cursor
            replacement.append(line[1:])
        else:
            raise HarnessError("invalid validated patch")
    flush()
    if _apply_edits(original, tuple(edits)) != after:
        raise HarnessError(f"cannot safely compose patch for {path}")
    return tuple(edits)


def _apply_edits(original: bytes, edits: tuple[_Edit, ...]) -> bytes:
    lines = original.decode("utf-8").splitlines(keepends=True)
    out: list[str] = []
    cursor = 0
    for edit in sorted(edits, key=lambda edit: (edit.start, edit.end)):
        if edit.start < cursor or edit.end < edit.start or edit.end > len(lines):
            raise HarnessError("overlapping base edits")
        out.extend(lines[cursor : edit.start])
        out.extend(edit.replacement)
        cursor = edit.end
    out.extend(lines[cursor:])
    return "".join(out).encode("utf-8")


def _overlap(a: _Edit, b: _Edit) -> bool:
    if a == b:
        return False  # exact duplicates are harmless and are deduplicated
    # Conservative: touching edits and insertions at a boundary conflict.
    return a.start <= b.end and b.start <= a.end


def compose_proposals(
    store: HarnessStore, baseline_id: str, proposals: tuple[Proposal, ...]
) -> Composition:
    """Persist a validated successor or return conflicts without writing.

    All proposals must independently apply exactly to the same base. Indices in
    conflicts refer to the input tuple. No refs or lineage are moved. Even an
    unconflicted composition is unapproved and must not be selected at runtime.
    """
    if type(proposals) is not tuple or not 1 <= len(proposals) <= MAX_PROPOSALS:
        raise HarnessError("expected 1 to 10 proposals")
    baseline = store.get_manifest(baseline_id)
    packaged = default_manifest()
    for path in TIER_0:
        if baseline.components[path] != packaged.components[path]:
            raise HarnessError(f"protected baseline component changed: {path}")
    base = {path: store.get_blob(baseline.components[path]) for path in EDITABLE}
    _validate_prompts(base)
    edits_by_path: dict[str, list[tuple[int, _Edit]]] = {}
    conflicts: set[Conflict] = set()
    for index, proposal in enumerate(proposals):
        if (
            type(proposal) is not Proposal
            or type(proposal.scope) is not str
            or proposal.scope not in {"invariant", "domain"}
            or type(proposal.path) is not str
            or proposal.path not in EDITABLE
            or type(proposal.diff) is not str
            or type(proposal.before_hash) is not str
            or type(proposal.after) is not bytes
        ):
            raise HarnessError("invalid proposal")
        original = base[proposal.path]
        if proposal.before_hash != content_hash(original):
            raise HarnessError("proposal baseline mismatch")
        after = apply_exact_diff(original, proposal.path, proposal.diff)
        if after != proposal.after:
            raise HarnessError("proposal result mismatch")
        edited = dict(base)
        edited[proposal.path] = after
        _validate_prompts(edited)
        fresh = _edits(original, proposal.path, proposal.diff, after)
        if len(set(fresh)) != len(fresh):
            raise HarnessError("ambiguous repeated edits in proposal")
        previous = edits_by_path.setdefault(proposal.path, [])
        for new in fresh:
            for previous_index, old in previous:
                if previous_index != index and _overlap(new, old):
                    conflicts.add(Conflict(proposal.path, previous_index, index))
        previous.extend((index, edit) for edit in fresh)
    if conflicts:
        return Composition(
            baseline_id,
            None,
            (),
            tuple(sorted(conflicts, key=lambda c: (c.path, c.first, c.second))),
        )
    combined = dict(base)
    for path, indexed in edits_by_path.items():
        combined[path] = _apply_edits(base[path], tuple(dict.fromkeys(edit for _, edit in indexed)))
    _validate_prompts(combined)
    changed = tuple(sorted(path for path in EDITABLE if combined[path] != base[path]))
    if not changed:
        raise HarnessError("composition makes no changes")
    components = dict(baseline.components)
    for path in changed:
        components[path] = store.put_blob(combined[path])
    candidate = store.put_manifest(
        Manifest(baseline.schema_version, baseline.model_pin, MappingProxyType(components))
    )
    return Composition(baseline_id, candidate, changed, ())
