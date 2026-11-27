"""ARCEN — agent-level reasoning loop.

GLM-5.4 runs a *shared block of layers* for several iterations, refining the
same hidden state each pass. That is a property of the neural network and
nothing in this package reproduces it: ARCEN cannot open a provider's KV
cache, cannot re-enter a forward pass, and does not train weights.

What transfers is the *control policy* around repeated refinement:

- decide how much depth a task deserves before spending tokens
  (:mod:`arcen.reasoning.complexity`);
- gate each refinement so a pass can be preserved, partially applied,
  replaced, or refused for lack of evidence (:mod:`arcen.reasoning.gate`);
- verify a candidate against evidence rather than against itself
  (:mod:`arcen.reasoning.verify`);
- stop when another pass stops paying for itself
  (:mod:`arcen.reasoning.loop`);
- persist pass state so a long run can be inspected after a crash
  (:mod:`arcen.reasoning.checkpoint`).

The distinction is load-bearing: this is iterative reasoning over *artifacts
and claims*, not looped computation over hidden states.
"""

from arcen.reasoning.checkpoint import CheckpointStore, LoopCheckpoint
from arcen.reasoning.complexity import Complexity, estimate_complexity
from arcen.reasoning.gate import (
    MODIFY,
    PRESERVE,
    REPLACE,
    REQUEST_INFO,
    GateDecision,
    UpdateGate,
)
from arcen.reasoning.loop import (
    Candidate,
    LoopResult,
    PassContext,
    PassOutput,
    PassRecord,
    RefinementLoop,
)
from arcen.reasoning.verify import (
    Observation,
    Verdict,
    check_observations,
    llm_verdict,
)

__all__ = [
    "MODIFY",
    "PRESERVE",
    "REPLACE",
    "REQUEST_INFO",
    "Candidate",
    "CheckpointStore",
    "Complexity",
    "GateDecision",
    "LoopCheckpoint",
    "LoopResult",
    "Observation",
    "PassContext",
    "PassOutput",
    "PassRecord",
    "RefinementLoop",
    "UpdateGate",
    "Verdict",
    "check_observations",
    "estimate_complexity",
    "llm_verdict",
]
