"""Bounded-scope read-only SQLite integrity/schema checks for harness doctor.

Local files are trusted against hostile concurrent substitution. Checks are
separate snapshots, not a transaction across databases and objects. SQLite WAL
may use sidecar files; this does not change refs, budgets, reviews or plans.
"""

from __future__ import annotations

import sqlite3
import stat
from contextlib import closing

from .resolver import HarnessError
from .store import HarnessStore

_DATABASES = (
    "tasks.sqlite3",
    "reviews.sqlite3",
    "campaigns.sqlite3",
    "budgets.sqlite3",
    "trial_slots.sqlite3",
    "experience.sqlite3",
)


def audit_auxiliary_databases(store: HarnessStore) -> int:
    """Check present, fixed-name databases; do not create absent databases.

    Performs SQLite quick_check and application schema validation. It is not a
    full record, provenance, authorization, or cross-database consistency audit.
    The existing doctor separately validates task entries and their objects.
    """
    if type(store) is not HarnessStore:
        raise HarnessError("invalid store for database audit")
    count = 0
    for name in _DATABASES:
        path = store.root / name
        try:
            info = path.lstat()
        except FileNotFoundError:
            continue
        except OSError:
            raise HarnessError(f"cannot inspect auxiliary database: {name}") from None
        if not stat.S_ISREG(info.st_mode):
            raise HarnessError(f"invalid auxiliary database: {name}")
        try:
            with closing(
                sqlite3.connect(path.absolute().as_uri() + "?mode=ro", uri=True, timeout=10)
            ) as db:
                db.execute("PRAGMA query_only=ON")
                db.execute("PRAGMA trusted_schema=OFF")
                if db.execute("PRAGMA quick_check(1)").fetchone() != ("ok",):
                    raise HarnessError("SQLite quick check failed")
                if name == "experience.sqlite3":
                    from .experience_cli_store import _validate

                    _validate(db)
            if name == "tasks.sqlite3":
                from .task_bank import TaskBank

                TaskBank(store)
            elif name == "reviews.sqlite3":
                from .review import ReviewLedger

                ReviewLedger(store)
            elif name == "campaigns.sqlite3":
                from .campaign_journal import CampaignJournal

                CampaignJournal(store)
            elif name == "budgets.sqlite3":
                from .durable_budget import DurableBudget

                DurableBudget.validate_database_schema(store)
            elif name == "trial_slots.sqlite3":
                from .durable_trial_slots import DurableTrialSlots

                DurableTrialSlots.validate_database_schema(store)
        except (sqlite3.Error, OSError, HarnessError):
            raise HarnessError(f"invalid auxiliary database: {name}") from None
        count += 1
    return count
