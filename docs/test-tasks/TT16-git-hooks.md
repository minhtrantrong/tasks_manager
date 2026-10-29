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

## Test environment

| | |
|---|---|
| Surface | Terminal CLI (`pytest`) driving a real `git` repository; no server |
| Command | `python -m pytest tests/test_hooks.py -v` |
| Setup | `python -m pip install -e ".[dev]"`; `git` on `PATH` and configured with a user |
| Env | `TASKS_DB=<repo>\.tmp-tt16\tasks.sqlite`; `git_repo` fixture under `tmp_path` |
| Prereqs | Git ≥2.30; cases 6–7 must run even where `git` is absent |

## Test data

- `git_repo`: `git init` in `tmp_path`, one initial commit, `core.autocrlf=false`.
- Hook config in `.tasks/config.json`:
  `{"hooks": {"enabled": true, "worktree": false, "commit_on_complete": true}}`
  and variants with `worktree: true` and `enabled: false` (default).
- Titles for case 1 and case 9: `"Fix plugin loader crash on startup"`,
  `"12; drop table tasks && echo $() 'quoted'"`, a unicode title, and a 300-char
  title.
- Failure injection: a fake runner that raises on `git commit`, plus
  `shutil.which("git") → None` for case 7.
- A project whose `root_path` was deleted between creation and transition.

## How to test

1. `python -m pytest tests/test_hooks.py -v` with the recorder running.
2. Run the naming group — `-k branch or sanit` — saving the four generated names
   into `attachments/branch-names.txt`.
3. Run the enabled group — `-k "enabled or worktree or commit"` — then show the
   branch and commit with `git log --oneline --all` and `git branch --list`.
4. Run the degradation group — `-k "non_git or no_git or failure or missing_root"`
   — proving the transition still succeeds and the journal records a warning.
5. Save `git log`, `git status --porcelain`, and `.tasks/worktrees/` listings into
   `attachments/git-log.txt`.

## Expected results

| Case | Expectation |
|---|---|
| 1 | `branch_name(12, "Fix plugin loader crash on startup") == "12-fix-plugin-loader-crash"`; punctuation, unicode and long titles sanitise deterministically |
| 2 | hooks off by default: `task_start` on a git repo creates no branch and no worktree |
| 3 | enabled `task_start` creates branch `<id>-<slug4>` from HEAD in the repo at `root_path` |
| 4 | `worktree=true` creates `.tasks/worktrees/<id>` and the branch; a second start reuses the path without failing |
| 5 | `commit_on_complete` makes exactly one commit on a dirty tree and is a silent no-op on a clean tree |
| 6 | a non-git `root_path` still transitions, journals a warning, and leaves status/owner/lease unaffected |
| 7 | with `git` missing, the same graceful path runs with no exception and no partial state |
| 8 | a failing hook command never rolls back the transition: the task stays `in_progress` with a lease and the warning is journalled |
| 9 | a title containing `;`, `&&`, `$()` or quotes cannot alter the command executed (argument-capture fake runner) |
| 10 | a missing `root_path` degrades exactly like case 6 |

## Test artifacts

Folder `docs/test-reports/TT16/` — layout and capture commands in
[test-reports/README.md](../test-reports/README.md).

| Path | Must show |
|---|---|
| `test-report.md` | verdict, 10 case rows, `git --version`, embedded screenshots, video link |
| `pytest.log` | full run plus the naming, enabled and degradation selections |
| `screenshots/01-branch-created.png` | `git branch --list` and `git log --oneline` after an enabled start/complete |
| `screenshots/02-hook-failure-graceful.png` | the failing-command run leaving `in_progress` plus the journal warning |
| `screenshots/03-no-shell-interpolation.png` | the captured argv for the hostile title, unchanged by shell metacharacters |
| `attachments/branch-names.txt` | the four sanitised names from case 1 |
| `attachments/git-log.txt` | `git log`, `git status --porcelain`, worktree listing |
| `video/TT16-git-hooks.mp4` | 30 s–5 min: suite, branch creation, failure injection, hostile title |

## Oracles exercised

OR-03 (warning journalled), N5 (Windows paths, no POSIX shell), plan §13.1.

## Done when

- `pytest tests/test_hooks.py -q` green on all three OSes (skips are not acceptable
  for cases 1, 5, 6, 7 — those must run everywhere `git` is available, and 6/7 must
  run even without it).
- No test asserts on locale-dependent git output.
- `docs/test-reports/TT16/` holds `test-report.md`, `pytest.log`,
  every screenshot embedded in the report, and the `video/TT16-git-hooks.mp4`
  recording.
