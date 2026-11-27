"""ARCEN — skills as tools (Part 2 row 5 made reachable).

The skills loader indexes ``SKILL.md`` frontmatter at boot and reads bodies on
demand. That design only pays off if the agent can ask for a body, which needs
a tool — until now nothing in a turn could reach the loader at all.

``skill.list`` returns the index (name, description, allowed tools): a few
lines per skill, cheap enough to call whenever the plan is unclear.
``skill.load`` returns one body, the procedure the agent should follow. Both
are read-only and host-side: skill files live next to the configuration, not
inside the turn snapshot.

An unknown name is an error that lists what does exist, because a model that
guessed wrong needs the correction in the same breath.
"""

from __future__ import annotations

from pydantic import BaseModel, Field

from ..skills.loader import SkillsLoader
from .registry import BaseTool

MAX_BODY_CHARS = 12_000


class _SkillsArgs(BaseModel):
    pass


class SkillList(BaseTool):
    name = "skill.list"
    description = (
        "List installed skills (name, description, allowed tools) to find a procedure for the task."
    )
    danger = "safe"

    Args = _SkillsArgs

    def __init__(self, loader: SkillsLoader | None = None, index: dict | None = None) -> None:
        self._loader = loader
        self._index = index

    def _run(self, a: _SkillsArgs) -> dict:
        index = (
            self._index
            if self._index is not None
            else (self._loader.index() if self._loader is not None else {})
        )
        return {
            "skills": [
                {
                    "name": meta.name,
                    "version": meta.version,
                    "description": meta.description,
                    "tools": list(meta.tools),
                }
                for meta in sorted(index.values(), key=lambda m: m.name)
            ],
            "count": len(index),
        }


class SkillLoad(BaseTool):
    name = "skill.load"
    description = "Load one skill's full procedure by name; follow it for the rest of the task."
    danger = "safe"

    class Args(BaseModel):
        name: str = Field(min_length=1, max_length=120, description="skill name from skill.list")

    def __init__(self, loader: SkillsLoader | None = None, index: dict | None = None) -> None:
        self._loader = loader
        self._index = index

    def _run(self, a: Args) -> dict:
        index = (
            self._index
            if self._index is not None
            else (self._loader.index() if self._loader is not None else {})
        )
        meta = index.get(a.name)
        if meta is None:
            available = sorted(index)
            raise ValueError(
                f"unknown skill {a.name!r}"
                + (f"; available: {', '.join(available)}" if available else "; no skills installed")
            )
        if self._loader is None:
            raise ValueError("skills loader is not configured")
        skill = self._loader.load(a.name, index)
        body = skill.body[:MAX_BODY_CHARS]
        return {
            "name": skill.meta.name,
            "version": skill.meta.version,
            "description": skill.meta.description,
            "tools": list(skill.meta.tools),
            "body": body,
            "truncated": len(skill.body) > MAX_BODY_CHARS,
        }
