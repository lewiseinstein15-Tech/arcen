"""Read-only rendering of local manual-campaign progress metadata.

This is not wired to the live server event stream. Progress is best-effort,
unsigned and non-authoritative; it never grants approval or changes refs.
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
        title = "candidate · static review"
        body.append(f"{event['candidate_id'][:12]} · reviewed, not approved")
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
        body.append("Human attention required. No adoption occurred.", style=TOKENS["muted"])
        accent = TOKENS["amber"]
    else:
        title = "campaign · finished" if event["status"] == "completed" else "campaign · stopped"
        body.append(f"{event['completed']} candidate(s) recorded")
        if event["reason"]:
            body.append(f" · {event['reason']}")
        body.append("\nNo candidate was adopted.", style=TOKENS["muted"])
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
