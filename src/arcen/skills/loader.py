"""ARCEN — skills loader (BACKEND-SPEC Part 2 row 5).

Pulled from Anthropic Skills (loader + registry pattern).

Edited per the Pull Map: progressive loading. A skill is a folder with a
``SKILL.md``; YAML frontmatter is indexed at boot (names, descriptions,
tool scopes), and the body is read from disk only when a task matches.
Indexing 10,000 skills therefore costs one stat+small-read per skill,
never the full bodies.

Skills scope what a sub-agent may do: a spawned worker's tool calls are
constrained to the skill's ``tools`` list when one is attached.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path

import yaml

FRONTMATTER_RE = re.compile(r"\A---\s*\n(.*?)\n---\s*\n?", re.DOTALL)


@dataclass
class SkillMeta:
    """The boot-time index entry — frontmatter only."""

    name: str
    version: str
    description: str
    tools: list[str]
    path: Path


@dataclass
class Skill:
    """A loaded skill: metadata plus the body (loaded on match)."""

    meta: SkillMeta
    body: str = ""
    metadata: dict = field(default_factory=dict)


class SkillsLoader:
    """Indexes skill folders; loads bodies lazily."""

    def __init__(self, paths: list[str] | None = None) -> None:
        self.paths = [Path(p).expanduser() for p in (paths or ["~/.arcen/skills", "./skills"])]

    # -- boot: index frontmatter only ---------------------------------------
    def index(self) -> dict[str, SkillMeta]:
        """Walk skill paths, parse each SKILL.md frontmatter into the index."""
        index: dict[str, SkillMeta] = {}
        for root in self.paths:
            if not root.is_dir():
                continue
            for skill_md in sorted(root.glob("*/SKILL.md")):
                parsed = _parse_frontmatter(skill_md)
                if parsed is None:
                    continue  # malformed skill folders are skipped, never fatal
                meta = parsed
                if meta.name in index:
                    continue  # first path wins; duplicates are not fatal
                index[meta.name] = meta
        return index

    # -- match: pick skills for a task ----------------------------------------
    def match(self, task: str, index: dict[str, SkillMeta] | None = None) -> list[SkillMeta]:
        """Skills whose name/description keywords appear in the task text."""
        idx = index if index is not None else self.index()
        task_lower = task.lower()
        words = set(re.findall(r"[a-z0-9_-]+", task_lower))
        hits: list[tuple[int, SkillMeta]] = []
        for meta in idx.values():
            score = 0
            hay_name = set(re.findall(r"[a-z0-9_-]+", meta.name.lower()))
            hay_desc = set(re.findall(r"[a-z0-9_-]+", meta.description.lower()))
            score += 3 * len(words & hay_name)
            score += 1 * len(words & hay_desc)
            if score > 0:
                hits.append((score, meta))
        hits.sort(key=lambda pair: pair[0], reverse=True)
        return [meta for _, meta in hits]

    # -- load: body on demand ----------------------------------------------------
    def load(self, name: str, index: dict[str, SkillMeta] | None = None) -> Skill:
        idx = index if index is not None else self.index()
        meta = idx.get(name)
        if meta is None:
            raise KeyError(f"unknown skill {name!r}")
        body, metadata = _read_body(meta.path)
        return Skill(meta=meta, body=body, metadata=metadata)


def _parse_frontmatter(path: Path) -> SkillMeta | None:
    """Parse only the frontmatter — the body is never read here."""
    try:
        text = path.read_text(encoding="utf-8")
    except OSError:
        return None
    m = FRONTMATTER_RE.match(text)
    if not m:
        return None
    try:
        data = yaml.safe_load(m.group(1)) or {}
    except yaml.YAMLError:
        return None
    name = data.get("name")
    description = data.get("description")
    if not name or not description:
        return None  # name and description are the minimum contract
    return SkillMeta(
        name=str(name),
        version=str(data.get("version", "0.0.0")),
        description=str(description),
        tools=[str(t) for t in (data.get("tools") or [])],
        path=path,
    )


def _read_body(path: Path) -> tuple[str, dict]:
    """The progressive-load step: read the file and split body from frontmatter."""
    text = path.read_text(encoding="utf-8")
    m = FRONTMATTER_RE.match(text)
    if not m:
        return text, {}
    try:
        metadata = yaml.safe_load(m.group(1)) or {}
    except yaml.YAMLError:
        metadata = {}
    return text[m.end() :].lstrip("\n"), metadata
