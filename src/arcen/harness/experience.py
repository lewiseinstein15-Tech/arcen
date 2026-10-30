"""Manually curated, review-linked lessons in the existing memory graph.

This is not an autonomous reflector and does not feed lessons into prompts.
The memory database and Python caller are trusted; review records are unsigned.
"""

from __future__ import annotations

import html
import json
import math
import re
import time
import unicodedata
from dataclasses import dataclass

from arcen.memory.store import MemoryStore
from arcen.plugins.redact_secrets import redact_text

from .resolver import HarnessError
from .review import ReviewLedger

_ENTITY = "arcen:harness:manual-lessons:v1"
_TOPIC = re.compile(r"[a-z0-9][a-z0-9-]{0,63}\Z")
MAX_LESSON_BYTES = 2048
MAX_ACTIVE_TOPICS = 100
MAX_AGE_SECONDS = 30 * 86400


@dataclass(frozen=True, slots=True)
class Lesson:
    fact_id: int
    topic: str
    text: str
    review_id: str
    baseline_id: str
    candidate_id: str
    created_at: float
    expires_at: float
    score: float


def _validate_topic(topic: str) -> None:
    if type(topic) is not str or not _TOPIC.fullmatch(topic):
        raise HarnessError("invalid lesson topic")


def _validate_text(text: str) -> None:
    if type(text) is not str or not text.strip() or text != text.strip():
        raise HarnessError("invalid lesson text")
    try:
        size = len(text.encode("utf-8"))
    except UnicodeError:
        raise HarnessError("lesson must be valid UTF-8") from None
    if size > MAX_LESSON_BYTES or any(
        unicodedata.category(c) in {"Cc", "Cf", "Zl", "Zp"} for c in text
    ):
        raise HarnessError("invalid or oversized lesson text")
    if redact_text(text) != text:
        raise HarnessError("lesson contains a detected secret")


def _approved(ledger: ReviewLedger, identifier: str):
    review = ledger.get(identifier)
    if review.state != "approved" or review.source != "paired":
        raise HarnessError("lesson requires an approved paired review record")
    return review


class ExperienceLibrary:
    """Manual observations only; callers must serialize access to MemoryStore."""

    def __init__(self, memory: MemoryStore, reviews: ReviewLedger):
        if type(memory) is not MemoryStore or type(reviews) is not ReviewLedger:
            raise HarnessError("invalid experience dependencies")
        if (
            type(memory.half_life_days) not in (int, float)
            or not math.isfinite(memory.half_life_days)
            or memory.half_life_days <= 0
        ):
            raise HarnessError("invalid memory decay setting")
        self.memory = memory
        self.reviews = reviews

    def record(self, topic: str, text: str, review_id: str, *, reviewed: bool = False) -> dict:
        """Record a caller-reviewed lesson; no editor or ref is touched."""
        if reviewed is not True:
            raise HarnessError("explicit lesson review is required")
        _validate_topic(topic)
        _validate_text(text)
        review = _approved(self.reviews, review_id)
        now = time.time()
        if not math.isfinite(now) or now < 0:
            raise HarnessError("invalid wall clock")
        if review.decided_at is None or now < review.decided_at:
            raise HarnessError("wall clock predates the review decision")
        conn = self.memory.conn
        latest = conn.execute(
            "SELECT MAX(valid_from) FROM facts WHERE entity=?", (_ENTITY,)
        ).fetchone()[0]
        if latest is not None:
            if type(latest) not in (int, float) or not math.isfinite(latest) or latest < 0:
                raise HarnessError("invalid experience history")
            if now < latest:
                raise HarnessError("wall clock moved backwards; lesson not recorded")
        count = conn.execute(
            "SELECT COUNT(DISTINCT key) FROM facts WHERE entity=? AND archived=0 AND invalid_at IS NULL",
            (_ENTITY,),
        ).fetchone()[0]
        current = conn.execute(
            "SELECT 1 FROM facts WHERE entity=? AND key=? AND archived=0 AND invalid_at IS NULL",
            (_ENTITY, topic),
        ).fetchone()
        if current is None and count >= MAX_ACTIVE_TOPICS:
            raise HarnessError("experience topic limit reached")
        payload = json.dumps(
            {
                "review_id": review.id,
                "baseline_id": review.baseline_id,
                "candidate_id": review.candidate_id,
                "text": text,
            },
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        )
        return self.memory.write(_ENTITY, payload, key=topic, source="review:" + review.id, ts=now)

    def active(self, *, as_of: float | None = None) -> tuple[Lesson, ...]:
        """Return bounded, non-expired lessons without touching their recency."""
        now = time.time() if as_of is None else as_of
        if type(now) not in (int, float) or not math.isfinite(now) or now < 0:
            raise HarnessError("invalid experience time")
        # One extra detects overfull or tampered stores rather than truncating.
        try:
            rows = self.memory.recall(_ENTITY, k=MAX_ACTIVE_TOPICS + 1, as_of=now, touch=False)
        except (ValueError, TypeError, ArithmeticError, KeyError):
            raise HarnessError("invalid experience record") from None
        if len(rows) > MAX_ACTIVE_TOPICS:
            raise HarnessError("experience topic limit exceeded")
        lessons = []
        seen: set[str] = set()
        for row in rows:
            topic = row["key"]
            _validate_topic(topic)
            if topic in seen:
                raise HarnessError("ambiguous active experience topic")
            seen.add(topic)
            created, score = row["created_at"], row["score"]
            if (
                type(created) not in (int, float)
                or not math.isfinite(created)
                or created < 0
                or created > now
                or type(score) not in (int, float)
                or not math.isfinite(score)
            ):
                raise HarnessError("invalid experience record")
            if now >= created + MAX_AGE_SECONDS:
                continue
            try:
                data = json.loads(row["fact"])
            except (ValueError, TypeError):
                raise HarnessError("invalid experience record") from None
            if type(data) is not dict or set(data) != {
                "review_id",
                "baseline_id",
                "candidate_id",
                "text",
            }:
                raise HarnessError("invalid experience record")
            _validate_text(data["text"])
            review = _approved(self.reviews, data["review_id"])
            if (
                type(row["sources"]) is not list
                or any(type(source) is not str for source in row["sources"])
                or data["baseline_id"] != review.baseline_id
                or data["candidate_id"] != review.candidate_id
                or "review:" + review.id not in row["sources"]
            ):
                raise HarnessError("experience provenance mismatch")
            lessons.append(
                Lesson(
                    row["id"],
                    topic,
                    data["text"],
                    review.id,
                    review.baseline_id,
                    review.candidate_id,
                    created,
                    created + MAX_AGE_SECONDS,
                    score,
                )
            )
        return tuple(lessons)

    def render(self, *, as_of: float | None = None) -> str:
        """Render for a person, never automatically inject into a model."""
        lessons = self.active(as_of=as_of)
        lines = [
            "# Manually reviewed experience",
            "",
            "Untrusted local notes; not policy, proof, or instructions.",
            "",
        ]
        for lesson in sorted(lessons, key=lambda item: item.topic):
            safe = html.escape(lesson.text, quote=False)
            safe = re.sub(r"([\\`*_\[\]()#!|])", r"\\\1", safe)
            lines.append(f"- **{lesson.topic}**: {safe} (review `{lesson.review_id}`)")
        if not lessons:
            lines.append("No active lessons.")
        return "\n".join(lines) + "\n"
