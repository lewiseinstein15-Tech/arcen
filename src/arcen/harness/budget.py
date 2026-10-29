"""In-process shared admission accounting, not a full campaign governor.

Only operations that explicitly share this object are counted. This object does
not cancel in-flight work, meter tokens/USD, persist across process restarts, or
control a trusted judge callback's internals.
"""

from __future__ import annotations

import math
import threading
import time
from dataclasses import dataclass

from .resolver import HarnessError


class BudgetExhausted(HarnessError):
    """No new budgeted work may start."""


@dataclass(frozen=True, slots=True)
class BudgetSnapshot:
    trials: int
    model_calls: int
    judge_calls: int
    stopped: bool
    reason: str | None
    elapsed_seconds: float


class SharedBudget:
    """Atomic, conservative reservations shared by explicitly bound trials.

    A failed attempt is consumed, not refunded. Stop, expiry and a rejected
    reservation latch the budget closed. In-flight work is not cancelled.
    The monotonic deadline is an admission cutoff, not a hard runtime timeout.
    """

    def __init__(
        self,
        *,
        max_trials: int,
        max_model_calls: int,
        max_judge_calls: int,
        admission_seconds: float,
    ):
        if any(
            type(x) is not int or not 0 <= x <= 100000
            for x in (max_trials, max_model_calls, max_judge_calls)
        ):
            raise HarnessError("invalid shared budget limits")
        if (
            max_trials < 1
            or type(admission_seconds) not in (int, float)
            or not math.isfinite(admission_seconds)
            or not 0.1 <= admission_seconds <= 86400
        ):
            raise HarnessError("invalid shared budget limits")
        self._limits = {
            "trials": max_trials,
            "model_calls": max_model_calls,
            "judge_calls": max_judge_calls,
        }
        self._used = dict.fromkeys(self._limits, 0)
        self._lock = threading.Lock()
        self._start = time.monotonic()
        self._deadline = self._start + admission_seconds
        self._reason: str | None = None

    def _check(self) -> None:
        if self._reason is None and time.monotonic() >= self._deadline:
            self._reason = "admission deadline reached"
        if self._reason is not None:
            raise BudgetExhausted("shared budget closed: " + self._reason)

    def checkpoint(self) -> None:
        with self._lock:
            self._check()

    def _reserve(self, category: str) -> None:
        with self._lock:
            self._check()
            if self._used[category] >= self._limits[category]:
                self._reason = category + " limit reached"
                raise BudgetExhausted("shared budget closed: " + self._reason)
            self._used[category] += 1

    def reserve_trial(self) -> None:
        self._reserve("trials")

    def reserve_model_call(self) -> None:
        self._reserve("model_calls")

    def reserve_judge_call(self) -> None:
        self._reserve("judge_calls")

    def stop(self) -> None:
        with self._lock:
            if self._reason is None:
                self._reason = "stopped"

    def snapshot(self) -> BudgetSnapshot:
        with self._lock:
            now = time.monotonic()
            if self._reason is None and now >= self._deadline:
                self._reason = "admission deadline reached"
            return BudgetSnapshot(
                self._used["trials"],
                self._used["model_calls"],
                self._used["judge_calls"],
                self._reason is not None,
                self._reason,
                max(0.0, now - self._start),
            )
