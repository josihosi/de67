# Alignment audit of the final integration review

The audit follows the intended named-worker workflow and the current CAOL specification layout. Review findings are claims to assess, not automatic release requirements.

**Full access is intentional.** The owner explicitly requires full access for these agents. The proposed sandbox restriction was rejected and its unmerged implementation and tests were reverted.

**The specification setup failure is real and reachable.** The current CAOL workspace has a canonical `FS.md` with `Status: Refrozen`; its `DFS.md` contains only a hash-bound compatibility pointer. The documented setup entrypoint reads `DFS.md` directly and searches that pointer for the status, rejecting an otherwise valid layout. A real configure fixture with bound accepted state reproduces this rejection. The narrow remedy is to use the existing specification resolver and include the canonical file when preparing the temporary acceptance projection. This removes an administrative mismatch while preserving the frozen-status and pointer-integrity checks. It does not require changing the specification, replaying proof, or starting production.

**The all-green legacy finding is outside the demonstrated current failure.** A focused reproduction shows an older guard CLI reports a completed legacy claim as ready when its slice markers remain. The current canonical FS path takes delivery state from the ledger and durable state, and no direct use of that legacy validator was found in worker dispatch. The finding therefore does not establish a blocker for this named-worker update. Its proposed stricter legacy gate and added tests were dropped from the change.

Identity, ownership, immutable evidence and single-use transitions should remain strict. Retrieval depth, task strategy and the choice to reuse workers remain agent decisions. The audit adds no runtime gate or recurring required read.
