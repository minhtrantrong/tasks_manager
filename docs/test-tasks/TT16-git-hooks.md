# TT16 — Optional git hooks

| | |
|---|---|
| Suite | `HK` |
| Verifies | [T16](../tasks/T16-git-hooks.md) |
| Phase | M5 |
| Depends on | TT07 |
| Unblocks | — |
| Level | L2 |
| Size | M |
| Status | pending |

## Goal

Prove git integration is opt-in, Windows-safe, and can never break a transition.

## Files

- `tests/test_hooks.py` — new.

## Cases

1. `branch_name(12, "Fix plugin loader crash on startup") ==
   "12-fix-plugin-loader-crash"`; punctuation, unicode, and very long titles are
   sanitised deterministically (same input → same name).
2. Hooks are off by default: `task_start` on a git repo creates no branch and no
   worktree when the project does not enable them.
3. Enabled `task_start` creates branch `<id>-<slug4>` from the current HEAD in the
   repo at `root_path`.
4. `worktree=true` creates `.tasks/worktrees/<id>` and the branch; a second start
   reuses the existing worktree path without failing.
5. `commit_on_complete`: with a dirty tree, `task_complete` creates one commit on
   the branch with the expected message; with a clean tree it is a no-op and raises
   nothing.
6. Non-git `root_path`: the transition still succeeds and a hook warning is
   journalled; status, owner, and lease are unaffected.
7. `git` missing from `PATH` (monkeypatch `shutil.which` → `None`): same graceful
   path as case 6, no exception, no partial state.
8. Hook failure never rolls back the transition: inject a failing command and assert
   the task is still `in_progress` with a lease, and the journal records the warning.
9. No shell interpolation: a title containing `;`, `&&`, `$()`, or quotes cannot
   alter the command executed (assert with an argument-capture fake runner).
10. A transition on a project whose `root_path` no longer exists degrades exactly
    like case 6.

## Oracles exercised

OR-03 (warning journalled), N5 (Windows paths, no POSIX shell), plan §13.1.

## Done when

- `pytest tests/test_hooks.py -q` green on all three OSes (skips are not acceptable
  for cases 1, 5, 6, 7 — those must run everywhere `git` is available, and 6/7 must
  run even without it).
- No test asserts on locale-dependent git output.
