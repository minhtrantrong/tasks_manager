# T16 — Optional git work-on hooks

| | |
|---|---|
| Phase | M5 |
| Depends on | T07 |
| Unblocks | — |
| Size | S |
| Status | pending |

## Goal

Optional git ergonomics on `task_start`/`task_complete`: branch (and optionally
worktree) per task. Off by default; never a premise (intend §11).

## Files

- `src/task_manager/hooks.py` — new.
- `src/task_manager/config.py` — add a `hooks` section loader.
- `src/task_manager/repository.py` — call hooks after `task_start`/`task_complete`
  commits.
- `tests/test_hooks.py` — new.

## Config

`.tasks/config.json` may contain:

```json
{
  "slug": "my-project",
  "root_path": ".",
  "hooks": {
    "enabled": false,
    "worktree": false,
    "commit_on_complete": false
  }
}
```

Defaults: all false. `load_config` (T03) exposes `hooks: HookConfig` dataclass.

## hooks.py contract

```python
def branch_name(task_id: int, title: str) -> str
    # words = first 4 tokens of re.findall(r'[a-z0-9]+', title.lower())
    # f"{task_id}-{'-'.join(words)}"   (e.g. "12-fix-plugin-loader")

def on_task_start(project, task) -> None
def on_task_complete(project, task) -> None
```

`on_task_start` (only when `hooks.enabled`):

1. `root_path` must exist and be a git repo (`git -C root_path rev-parse`); if not,
   log a warning and return (never raise).
2. `worktree=false`: `git -C root_path checkout -b <branch>`.
3. `worktree=true`: `git -C root_path worktree add -b <branch> .tasks/worktrees/<id>`.

`on_task_complete` (only when `hooks.enabled` and `commit_on_complete`):

1. Repo = the worktree dir if `worktree=true`, else `root_path`.
2. If `git status --porcelain` is empty → return (nothing to commit).
3. `git add -A` then
   `git commit -m "task-manager: complete task #<id> — <title>"`.

**Windows-safety and robustness rules:**

- Use `subprocess.run([...], capture_output=True, text=True)` with explicit arg
  lists — **never** `shell=True`.
- Every hook failure logs a warning and appends a journal `note` ("hook warning:
  <stderr>") via the repository; it **never** fails or rolls back the transition
  (hooks run after commit).
- No network, no non-git binaries.

`repository.task_start`/`task_complete` call the hooks only when the project's
config has hooks enabled (repository looks up config via `load_config` cache).

## Tests (`tests/test_hooks.py`)

1. `branch_name(12, "Fix plugin loader crash on startup")` ==
   `"12-fix-plugin-loader-crash"`; titles with punctuation are sanitised.
2. Temp git repo (run `git init` in `tmp_path`): with hooks enabled, `task_start`
   creates branch `<id>-<slug4>`; with hooks disabled, no branch.
3. `worktree=true` creates `.tasks/worktrees/<id>` and the branch.
4. `commit_on_complete`: write a file, `task_complete` → commit exists on the
   branch with the expected message; clean tree → no commit, no error.
5. Non-git `root_path` → transition still succeeds, journal contains the hook
   warning, nothing raised.
6. `git` missing from PATH (monkeypatch `shutil.which` → None) → same graceful path.

## Done when

- Git integration works when opted in, degrades silently when not, and never
  breaks a transition (intend M5 gate).
- Tests green on all CI OSes (the matrix proves the Windows path).
