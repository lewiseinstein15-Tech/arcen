"""Read-only, human-facing filter of unsigned local comparison summaries.

This is an advisory view, not authenticated evidence, candidate selection,
execution approval or adoption. It does not know whether a judgment is correct.
"""

from __future__ import annotations

from dataclasses import dataclass

from .campaign_journal import CampaignJournal, CampaignRecord
from .manifest import default_manifest
from .policy import review_candidate
from .resolver import HarnessError
from .review import ReviewLedger, ReviewRecord
from .store import HarnessStore
from .task_bank import TaskBank


@dataclass(frozen=True, slots=True)
class ContrastItem:
    review: ReviewRecord
    changed_paths: tuple[str, ...]
    category: str


@dataclass(frozen=True, slots=True)
class ContrastSuggestions:
    campaign: CampaignRecord
    task_id: str
    workspace_sha256: str
    items: tuple[ContrastItem, ...]


def suggest_recorded_wins(
    store: HarnessStore, campaign_id: str, task_id: str
) -> ContrastSuggestions:
    """Classify all completed-campaign records using one narrow, transparent rule.

    A locally recorded candidate win that is not rejected is flagged for human
    inspection. Ties, reference wins and rejected reviews are shown but not
    suggested. Confidence is neither thresholded nor ranked. This reads trusted
    local state, does not authenticate it and is not an atomic snapshot.
    """
    if type(store) is not HarnessStore:
        raise HarnessError("invalid campaign store")
    journal = CampaignJournal(store)
    campaign = journal.get(campaign_id)
    if campaign.state != "completed":
        raise HarnessError("suggestions require a completed campaign")
    if task_id != campaign.task_sha256:
        raise HarnessError("task does not match the campaign plan")
    TaskBank(store).read(task_id)  # Verify that the exact stored task remains available.
    baseline = store.get_manifest(campaign.baseline)
    packaged = default_manifest()
    if (
        baseline.schema_version != packaged.schema_version
        or baseline.components != packaged.components
    ):
        raise HarnessError("suggestions require the unchanged packaged baseline")
    ledger = ReviewLedger(store)
    items = []
    for review_id, candidate in zip(campaign.reviews, campaign.candidates, strict=True):
        review = ledger.get(review_id)
        if (
            review.source != "paired"
            or review.baseline_id != campaign.baseline
            or review.candidate_id != candidate
            or review.commit != campaign.commit
        ):
            raise HarnessError("review metadata does not match the completed campaign")
        paths = review_candidate(store, campaign.baseline, candidate).changed_paths
        category = (
            "rejected"
            if review.state == "rejected"
            else "candidate-win"
            if review.judge_winner == "candidate"
            else "reference-win"
            if review.judge_winner == "reference"
            else "tie"
        )
        items.append(ContrastItem(review, paths, category))
    workspaces = {item.review.workspace_sha256 for item in items}
    if len(workspaces) != 1:
        raise HarnessError("reviews do not share a recorded workspace")
    # Catch ordinary cooperating mutations while building the view; not a lock,
    # transaction across databases or defense against hostile local writers.
    if journal.get(campaign_id) != campaign or any(
        ledger.get(item.review.id) != item.review for item in items
    ):
        raise HarnessError("campaign or reviews changed during suggestion")
    return ContrastSuggestions(campaign, task_id, workspaces.pop(), tuple(items))
