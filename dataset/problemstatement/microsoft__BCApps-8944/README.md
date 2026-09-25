# Fix PerItemCommit in cost adjustment and check for other patterns when the instance of the posting codeunit is reused after the COMMIT

## Repro Steps

### Background

Concurrent posting sessions intermittently hit a duplicate-key error on table 17 **G/L Entry** (BC tag `00000I0`, 7,953 occurrences in the last 14 days). The race occurs when a COMMIT lands between `CU12.StartPosting` (which calls `InitNextEntryNo` → `LockTable + FindLast` on G/L Entry and caches `NextEntryNo`) and the last `InsertGLEntry` of the posting batch. The lock is released while `NextEntryNo` is still cached in CU12 memory.

The cost-adjustment path (`Report 795` → `CU5895 InventoryAdjustment` → `CU22 ItemJnlPostLine` → `CU5802 InventoryPostingToGL` → `CU12 GenJnlPostLine`) is the only base-app source confirmed to commit inside this window, and it does so by design: the *Item-By-Item Commit* parameter causes `CU5895.CheckAndCommit` to fire a `Commit()` after each item. The problem disappeared for the reporting tenant when per-item commits were disabled.

### Why the cost-adjustment path is the cleanest base-app reproduction

In `CU5895 InventoryAdjustment`, `ItemJnlPostLine` is a member variable. `InitializeAdjmt` clears it once at startup but does not re-clear it between items. `CU22` in turn holds `CU5802` as a member, which holds `CU12` as a member. So a **single CU12 instance lives for the entire `Report 795` run - across every item**.

After `CheckAndCommit` commits, that CU12 instance still has `NextEntryNo`, `NextTransactionNo`, `NextVATEntryNo`, `FirstEntryNo`, `FirstNewVATEntryNo`, `IsGLRegInserted`, and `TempGLEntryBuf` all populated from the previous item. The next item's first gen-journal line hits the CU12 dispatcher with `NextEntryNo > 0`, so it takes the `ContinuePosting` fast-path - no `LockTable`, no `FindLast`. The next `InsertGLEntry` writes `NextEntryNo+1` using the stale cached value; a concurrent session that has inserted past that number in the meantime causes the duplicate-key error on the next `FinishPosting`.

Unlike the sales-posting path, this path is **never** under `CommitBehavior::Ignore` (it is invoked from `Report 795` directly), so the per-item commit always fires as a real platform commit.

### What must be done

1. In `CU5895.CheckAndCommit`, after the per-item `Commit()`, reset the cached transactional state on the inherited CU12 instance so the next `RunWithCheck` returns to the `StartPosting` path and re-runs `LockTable + FindLast` on the now-committed state. Concretely, expose a `ResetTransactionState` on `CU12` that zeros `NextEntryNo`, `NextTransactionNo`, `NextVATEntryNo`, `FirstEntryNo`, `FirstNewVATEntryNo`, `IsGLRegInserted`, and resets `TempGLEntryBuf`; passthrough on `CU5802` and `CU22`; call it from `CheckAndCommit` via the passthrough chain. Do not `Clear(ItemJnlPostLine)` wholesale - that would destroy `CalledFromAdjustment` / `PostToGL` set in `InitializeAdjmt` and other configure-once state on CU22 and CU5802.
2. Add telemetry around `CheckAndCommit` (FeatureTelemetry, with the items-since-last-commit count, nesting state, online-adjustment flag, post-to-GL flag, and item-by-item-commit flag as dimensions) so the rollout can be measured.
3. Audit and treat the same way every other base-app call site that holds a long-lived `CU12` instance across commits. Known suspects:
   * **IC gen-journal posting inside CU80** (`GenJnlPostLine.RunWithCheck(TempICGenJnlLine)`) - the same CU12 instance is reused after IC processing; if an extension commits inside an IC subscriber and the CU80 guard is bypassed via `OnSetCommitBehavior`, the same buffer-persistence problem occurs.
   * Any base-app orchestrator that calls `GenJnlPostLine.RunWithCheck(...)` repeatedly in a loop and may commit between iterations on the same instance.For each, decide whether to call `ResetTransactionState` after every potential commit point or to refuse to commit in that scope at all.
4. Document the contract: the new `ResetTransactionState` on `CU12` should be public so cautious ISV orchestrators that hold a long-lived CU12 instance can call it themselves after any commit they intentionally issue.

### Validation

* Run `Report 795` with `Item-By-Item Commit = true` against two concurrent sessions also performing sales/purchase posting; confirm zero `00000I0` duplicate-key errors over a sustained run.
* Confirm `CalledFromAdjustment` / `PostToGL` on `CU22` and `SetOverDimErr` on `CU5802` survive the reset (i.e., do not need to be re-issued by callers).
