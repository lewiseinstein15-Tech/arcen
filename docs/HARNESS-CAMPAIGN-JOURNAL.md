# Manual campaign journal (experimental)

`CampaignJournal` adds durable local bookkeeping to the experimental Python
manual comparison path. It does **not** enable autonomous execution, adoption or
safe automatic resume. The caller must still explicitly review the task,
candidates, commit and provider/judge exposure; flags are attestations, not
authenticated consent.

```python
from arcen.harness.campaign_journal import CampaignJournal
from arcen.harness.manual_campaign import run_manual_campaign

# Existing, explicitly reviewed values: store, baseline, candidates, task,
# config, judge, repo, commit, reviews and a DurableBudget for the same store.
journal = CampaignJournal(store, create=True)
plan = journal.plan(baseline, candidates, task, commit, budget=budget)
result = run_manual_campaign(
    store, baseline, candidates, task, config, judge,
    repo=repo, commit=commit, reviews=reviews, budget=budget,
    reviewed_inputs=True, reviewed_judge_inputs=True,
    journal=journal, campaign_id=plan.id,
)
print(journal.get(plan.id))
```

A plan records IDs, a SHA-256 digest of the task, commit, phase and review IDs;
it does not store task text or trajectories. Hashing is not encryption: a
predictable task can be guessed from its digest. Store data and paths should be
protected. The journal is unsigned; the local store, caller and filesystem are
trusted. The journal alone cannot prove who reviewed a plan or what actually ran.

A plan is claimed only once using an atomic database update. Journaled runs mark
reference, candidate, judge and review-recording stages; completed review IDs
are saved in candidate order. A stopped, failed, completed or already-running
plan cannot be claimed again. A crash leaves the last phase as `running`: the
record is **ambiguous**, not proof of whether a provider, judge or Docker action
finished. Do not automatically rerun it. The user must inspect pending review
records and any potentially orphaned containers. There is currently no lease,
process-liveness proof or automatic recovery/resume.

An initialized harness store can inspect or request stop from another terminal:

```sh
arcen harness --store /path/to/store campaign status CAMPAIGN_ID
arcen harness --store /path/to/store campaign stop CAMPAIGN_ID
```

A stop request is persisted and checked at stage boundaries. A previously
admitted Git operation, model call, judge callback, container or command may
continue or finish; this is **not immediate cancellation**. A review record
already being written is retained and journaled before the run stops. A stop
request on a crashed worker may remain pending indefinitely because no worker is
available to acknowledge it. Neither command starts, resumes or adopts a run.

Journal use is optional for backward compatibility with the manual Python API;
unjournaled runs have none of these persistence or stop properties. The run can
use an in-process or durable admission budget. New plans can bind a durable
budget ID; CLI plans require one. An existing legacy unbound plan stays unbound
and the CLI refuses to run it. Unbound Python API plans remain supported for
backward compatibility. A binding is local metadata, not authentication or an
atomic transaction with the separate budget database. The budget can expire or
be stopped between checks. Older database clients are blocked by a SQLite trigger
from claiming a bound plan, but do not mix software versions during a run.
Migration to schema version 2 occurs when a journal is opened with `create=True`;
read-only opens of version 1 do not migrate it. Neither option is a token/USD
cap or a hard runtime limit. Separate SQLite databases for the journal and review
ledger are not one atomic transaction: an error or crash during review recording
can leave a pending review without a matching journal entry. Never infer that a
missing entry means an external action did not occur. See
`HARNESS-MANUAL-CAMPAIGN.md` and `HARNESS-BUDGET.md` for remaining limitations.

The user reported the journaled manual campaign's opt-in real-Docker test
passed on Omarchy at `4ecaf6e`; model responses and judge were mocked. See
`docs/verify/README.md`.
