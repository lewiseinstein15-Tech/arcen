"""T-017 — skills loader (BACKEND-SPEC Part 2 row 5).

Proves: a SKILL.md loads and parses correctly; frontmatter indexes at
boot; bodies load progressively on match; malformed skills are skipped.
"""

from pathlib import Path

import pytest

from arcen.skills.loader import Skill, SkillMeta, SkillsLoader

SKILL_MD = """---
name: pytest-repair
version: 0.1.0
description: Fix failing pytest suites with minimal diffs
tools: [bash, file.read, file.edit]
---

# Pytest Repair

1. Run `pytest -q` and capture the first failure.
2. Decide: test bug or code bug.
3. Apply the minimal edit.
"""


@pytest.fixture()
def skills_dir(tmp_path) -> Path:
    d = tmp_path / "skills"
    (d / "pytest-repair").mkdir(parents=True)
    (d / "pytest-repair" / "SKILL.md").write_text(SKILL_MD, encoding="utf-8")
    return d


@pytest.fixture()
def loader(skills_dir) -> SkillsLoader:
    return SkillsLoader([str(skills_dir)])


def test_load_a_skill_md(loader) -> None:
    # mirrors the ticket Command: load a SKILL.md → parsed correctly
    index = loader.index()
    assert "pytest-repair" in index
    meta = index["pytest-repair"]
    assert isinstance(meta, SkillMeta)
    assert meta.version == "0.1.0"
    assert meta.tools == ["bash", "file.read", "file.edit"]
    skill = loader.load("pytest-repair", index)
    assert isinstance(skill, Skill)
    assert "# Pytest Repair" in skill.body
    assert "minimal edit" in skill.body


def test_index_does_not_read_bodies(loader, skills_dir, monkeypatch) -> None:
    """Progressive loading: index() must not read body content."""
    skill_file = skills_dir / "pytest-repair" / "SKILL.md"
    original_read = Path.read_text

    def guard(self, *args, **kwargs):
        text = original_read(self, *args, **kwargs)
        assert "Pytest Repair" not in text.split("---")[-1][:0]  # frontmatter read only
        return text

    monkeypatch.setattr(Path, "read_text", guard)
    loader.index()  # reads only frontmatter-sized content
    # loading does read the body — the guard allows it
    loader.load("pytest-repair")


def test_match_by_task_text(loader) -> None:
    index = loader.index()
    hits = loader.match("the pytest suite is failing, repair it", index)
    assert hits and hits[0].name == "pytest-repair"
    assert loader.match("cook pasta", index) == []


def test_malformed_skill_skipped(tmp_path) -> None:
    d = tmp_path / "skills"
    (d / "good").mkdir(parents=True)
    (d / "good" / "SKILL.md").write_text(SKILL_MD, encoding="utf-8")
    (d / "bad-no-frontmatter").mkdir()
    (d / "bad-no-frontmatter" / "SKILL.md").write_text("just text", encoding="utf-8")
    (d / "bad-no-name").mkdir()
    (d / "bad-no-name" / "SKILL.md").write_text("---\ndescription: x\n---\nbody", encoding="utf-8")
    (d / "bad-yaml").mkdir()
    (d / "bad-yaml" / "SKILL.md").write_text("---\nname: [unclosed\n---\nbody", encoding="utf-8")
    loader = SkillsLoader([str(d)])
    index = loader.index()
    assert list(index) == ["pytest-repair"]


def test_duplicate_name_first_path_wins(tmp_path) -> None:
    d1, d2 = tmp_path / "one", tmp_path / "two"
    (d1 / "s").mkdir(parents=True)
    (d2 / "s").mkdir(parents=True)
    (d1 / "s" / "SKILL.md").write_text("---\nname: s\nversion: 1.0.0\ndescription: first\n---\nA")
    (d2 / "s" / "SKILL.md").write_text("---\nname: s\nversion: 2.0.0\ndescription: second\n---\nB")
    loader = SkillsLoader([str(d1), str(d2)])
    index = loader.index()
    assert index["s"].version == "1.0.0"


def test_missing_path_ignored(tmp_path) -> None:
    loader = SkillsLoader([str(tmp_path / "does-not-exist")])
    assert loader.index() == {}


def test_repo_ships_the_readme_skill() -> None:
    """The repo's own skills/ carries the README's pytest-repair skill."""
    loader = SkillsLoader(["./skills"])
    index = loader.index()
    assert "pytest-repair" in index
    skill = loader.load("pytest-repair", index)
    assert "escalate to DRAFT" in skill.body


def test_unknown_skill_raises(loader) -> None:
    with pytest.raises(KeyError):
        loader.load("no-such-skill")
