"""Prepare manual composition from a completed, locally recorded campaign.

Records and judgments are unsigned and may be fabricated by local callers.
This module does not select a winner, authorize execution or adopt anything.
"""

from __future__ import annotations

import difflib
from dataclasses import dataclass, field

from .campaign_journal import CampaignJournal, CampaignRecord
from .composer import MAX_PROPOSALS
from .editor import MAX_PATCH_BYTES, Proposal, apply_exact_diff
from .manifest import default_manifest
from .model import content_hash
from .policy import review_candidate
from .resolver import HarnessError
from .review import ReviewLedger, ReviewRecord
from .store import HarnessStore
from .task_bank import TaskBank


@dataclass(frozen=True, slots=True)
class RecordedComposition:
    campaign: CampaignRecord
    reviews: tuple[ReviewRecord, ...]
    proposals: tuple[Proposal, ...] = field(repr=False)
    proposal_reviews: tuple[str, ...]
    task: str = field(repr=False)


def prepare_recorded_composition(
    store: HarnessStore, campaign_id: str, task_id: str, review_ids: tuple[str, ...]
) -> RecordedComposition:
    """Validate linked local metadata and reconstruct exact base-relative diffs.

    No objects, journals or refs are written. The caller must independently
    review the data before composing. This is not an authenticated evidence gate.
    """
    if (
        type(store) is not HarnessStore
        or type(review_ids) is not tuple
        or not 2 <= len(review_ids) <= 5
        or any(type(value) is not str for value in review_ids)
        or len(set(review_ids)) != len(review_ids)
    ):
        raise HarnessError("choose 2 to 5 distinct review IDs")
    campaign = CampaignJournal(store).get(campaign_id)
    if campaign.state != "completed":
        raise HarnessError("composition requires a completed campaign")
    task = TaskBank(store).read(task_id)
    if task_id != campaign.task_sha256:
        raise HarnessError("task does not match the campaign plan")
    linked = dict(zip(campaign.reviews, campaign.candidates, strict=True))
    ledger = ReviewLedger(store)
    selected = []
    for review_id in review_ids:
        if review_id not in linked:
            raise HarnessError("review is not linked to the completed campaign")
        record = ledger.get(review_id)
        if (
            record.source != "paired"
            or record.state == "rejected"
            or record.baseline_id != campaign.baseline
            or record.candidate_id != linked[review_id]
            or record.commit != campaign.commit
        ):
            raise HarnessError("review metadata does not match the campaign or is rejected")
        selected.append(record)
    if len({record.workspace_sha256 for record in selected}) != 1:
        raise HarnessError("reviews do not share a recorded workspace")
    baseline = store.get_manifest(campaign.baseline)
    packaged = default_manifest()
    if (
        baseline.schema_version != packaged.schema_version
        or baseline.components != packaged.components
    ):
        raise HarnessError("recorded composition requires the unchanged packaged baseline")
    proposals = []
    proposal_reviews = []
    for record in selected:
        changes = review_candidate(store, campaign.baseline, record.candidate_id).changed_paths
        candidate = store.get_manifest(record.candidate_id)
        for path in changes:
            if len(proposals) >= MAX_PROPOSALS:
                raise HarnessError("selected reviews exceed the composition proposal limit")
            original = store.get_blob(baseline.components[path])
            after = store.get_blob(candidate.components[path])
            if len(after) > len(original) + MAX_PATCH_BYTES:
                raise HarnessError("candidate component exceeds reconstruction limit")
            try:
                patch = "".join(
                    difflib.unified_diff(
                        original.decode("utf-8").splitlines(keepends=True),
                        after.decode("utf-8").splitlines(keepends=True),
                        fromfile="a/" + path,
                        tofile="b/" + path,
                    )
                )
                if len(patch.encode("utf-8")) > MAX_PATCH_BYTES:
                    raise HarnessError("reconstructed patch exceeds size limit")
            except UnicodeError:
                raise HarnessError("candidate component is not UTF-8") from None
            if apply_exact_diff(original, path, patch) != after:
                raise HarnessError("candidate diff reconstruction failed")
            # Scope isn't preserved by manifests and has no role in merging.
            proposals.append(Proposal("domain", path, patch, content_hash(original), after))
            proposal_reviews.append(record.id)
    return RecordedComposition(
        campaign, tuple(selected), tuple(proposals), tuple(proposal_reviews), task
    )
