"""Read-only rendering of local manual-campaign progress metadata.

The optional registration below can consume validated v2 progress when an
application explicitly connects it; the server is not wired to it. Progress is
best-effort, unsigned and non-authoritative; it never grants approval or changes refs.
"""

from __future__ import annotations

from rich.text import Text

from arcen.harness.progress import _validate
from arcen.harness.resolver import HarnessError
from arcen.tui.cards.base import spine_break, spine_card
from arcen.tui.theme import TOKENS


def _card(event: dict):
    kind = event["type"]
    body = Text()
    accent = TOKENS["cyan"]
    if kind == "harness.campaign.start":
        title = "campaign · started"
        body.append(f"{event['candidate_count']} candidate(s) · sequential manual comparison\n")
        body.append("Progress is unsigned, best-effort metadata.", style=TOKENS["muted"])
    elif kind == "harness.policy":
        title = "candidate · reported static review"
        body.append(f"{event['candidate_id'][:12]} · unverified, not approval")
    elif kind == "harness.probe.start":
        title = "trial · started"
        body.append(f"{event['role']} · {event['candidate_id'][:12]}")
    elif kind == "harness.probe.done":
        title = "trial · finished"
        body.append(f"{event['role']} · {event['candidate_id'][:12]} · {event['status']}")
        if event["status"] != "ok":
            accent = TOKENS["amber"]
    elif kind == "harness.judge":
        title = "comparison · local judgment"
        body.append(f"{event['winner']} · confidence {event['confidence']:.2f}\n")
        body.append(
            "Uncalibrated and unauthenticated; not an adoption decision.", style=TOKENS["muted"]
        )
    elif kind == "harness.review":
        title = "review · pending"
        body.append(f"Candidate {event['candidate_id'][:12]} · review {event['review_id'][:12]}\n")
        body.append("Unverified review; this view performs no adoption.", style=TOKENS["muted"])
        accent = TOKENS["amber"]
    else:
        title = (
            "campaign · reported finished"
            if event["status"] == "completed"
            else "campaign · reported stopped"
        )
        body.append(f"{event['completed']} candidate(s) recorded")
        if event["reason"]:
            body.append(f" · {event['reason']}")
        body.append("\nThis view performs no adoption.", style=TOKENS["muted"])
        accent = TOKENS["emerald"] if event["status"] == "completed" else TOKENS["amber"]
    return spine_card(body, title, accent)


class HarnessProgressView:
    """Render validated metadata only; rejects duplicates and malformed events."""

    def __init__(self, narration):
        self.narration = narration
        self.last_seq = 0
        self.accepted = 0

    def apply(self, event: object) -> bool:
        if type(event) is not dict:
            return False
        try:
            _validate(event)
            if event["seq"] <= self.last_seq:
                return False
            card = _card(event)
        except (HarnessError, TypeError, KeyError, ValueError, OverflowError):
            return False
        if self.accepted:
            self.narration.push(spine_break())
        self.narration.push(card)
        self.last_seq = event["seq"]
        self.accepted += 1
        return True


def register_v2_progress(adapter):
    """Opt in to metadata-only v2 cards on an existing event adapter.

    This does not start a campaign or connect the server. Malformed or
    unexpected fields are discarded, and unsigned records are not evidence.
    Existing handlers are never replaced.
    """
    from arcen.stream.events import EventError
    from arcen.stream.events_v2 import V2_PROGRESS_TYPES, progress_from_wire
    from arcen.tui.adapter import EventAdapter

    if type(adapter) is not EventAdapter:
        raise ValueError("expected a TUI event adapter")
    if any(kind in adapter.handlers for kind in V2_PROGRESS_TYPES):
        raise ValueError("v2 progress handler already registered")
    view = HarnessProgressView(adapter.narration)

    def handle(event):
        try:
            progress = progress_from_wire(event)
        except EventError:
            return
        view.apply(progress)

    for kind in V2_PROGRESS_TYPES:
        adapter.register_handler(kind, handle)
    return view
