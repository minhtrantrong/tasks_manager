# TT11 — `recall`: FTS5 with LIKE fallback

| | |
|---|---|
| Suite | `RCL` |
| Verifies | [T11](../tasks/T11-recall.md) |
| Phase | M3 |
| Depends on | TT09 |
| Unblocks | — |
| Level | L2 |
| Size | S |
| Status | pending |

## Goal

Prove "did we already try this?" is answerable from stored memory on every build,
including one without FTS5.

## Files

- `tests/test_recall.py` — new.

## Cases

1. Journal body "retry uses backoff 2^n" is found by the query `backoff retry`; the
   snippet contains the matched text and the hit carries the task id.
2. A task is found by title and, separately, by description.
3. `project_id` scoping: hits in another project are absent; omitting the project
   searches all non-archived projects.
4. `limit` is respected (5 returns ≤5) and journal hits precede task hits for the
   same query.
5. FTS syntax safety: queries containing `"`, `*`, `(`, `-`, `NEAR`, and an
   all-operator string return results or an empty list — never an `OperationalError`.
6. Blank or whitespace-only query → `ValidationError`.
7. Fallback: with `fts_enabled` monkeypatched False, the same three queries return
   results and `search_backend == "like"`; with FTS available it is `"fts"`.
8. `require_fts=True` with FTS unavailable → `FtsUnavailable`; the server still runs
   (no import-time failure).
9. Relevance sanity on `seed_large`: `recall("api key")` returns the one task whose
   journal mentions it, inside the top 3.
10. A hit for a soft-cancelled task is still returned but flagged with its status;
    a hard-deleted task leaves no hit (FTS triggers removed it).

## Test environment

| | |
|---|---|
| Surface | Terminal CLI (`pytest`); no server, no browser |
| Command | `python -m pytest tests/test_recall.py -v` |
| Setup | `python -m pip install -e ".[dev]"` |
| Env | `TASKS_DB=<repo>\.tmp-tt11\tasks.sqlite`; `fts_enabled()` monkeypatched for the fallback half |
| Prereqs | CPython 3.12; FTS5 present for the default path, simulated absent for cases 7–8 |

## Test data

- Journal body: `"retry uses backoff 2^n"` attached to a known task.
- Task pair: title `"Fix API key rotation"` and a description containing
  `"api key"` for the per-field search.
- Second project `other` containing a look-alike body, for the scoping case.
- Queries: `backoff retry`, `api key`, `"quoted"`, `foo*`, `(bar`, `-baz`,
  `NEAR(a b)`, `AND AND`, `""`, `"   "`.
- `seed_large` for the relevance sanity check (`recall("api key")` in the top 3).
- Statuses: one soft-cancelled task with a hit, one hard-deleted task with none.
- Limits: `limit=5` against a fixture with more than five matches.

## How to test

1. `python -m pytest tests/test_recall.py -v` with the recorder running.
2. Run the FTS group — `-k "fts or relevance"` — and screenshot `search_backend == "fts"`.
3. Run the fallback group — `-k "like or fallback"` — showing the same queries with
   `search_backend == "like"`.
4. Run the syntax-safety group — `-k "syntax or blank"` — showing no
   `OperationalError` for hostile queries.
5. Save the hit lists for the three canonical queries into
   `attachments/recall-hits.json`, with backend and limit noted.

## Expected results

| Case | Expectation |
|---|---|
| 1 | `backoff retry` finds the journal entry, the snippet contains the matched text, and the hit carries the task id |
| 2 | a task is found by title and, separately, by description |
| 3 | hits from another project are absent; omitting `project_id` searches all non-archived projects |
| 4 | `limit=5` returns at most five hits and journal hits precede task hits |
| 5 | every hostile query returns results or an empty list — never an `OperationalError` |
| 6 | a blank or whitespace-only query raises `ValidationError` |
| 7 | with `fts_enabled` False the same queries return results and `search_backend == "like"`; with FTS it is `"fts"` |
| 8 | `require_fts=True` without FTS raises `FtsUnavailable` while the server still runs |
| 9 | `recall("api key")` on `seed_large` returns the expected task within the top 3 |
| 10 | a soft-cancelled hit is returned and flagged with its status; a hard-deleted task leaves no hit |

## Test artifacts

Folder `docs/test-reports/TT11/` — layout and capture commands in
[test-reports/README.md](../test-reports/README.md).

| Path | Must show |
|---|---|
| `test-report.md` | verdict, 10 case rows, backend used per run, embedded screenshots, video link |
| `pytest.log` | full run plus the FTS, fallback and syntax-safety selections |
| `screenshots/01-fts-hit.png` | the journal hit with snippet and `search_backend == "fts"` |
| `screenshots/02-like-fallback.png` | the same query set with `search_backend == "like"` |
| `screenshots/03-syntax-safety.png` | hostile queries returning results or `[]`, no `OperationalError` |
| `attachments/recall-hits.json` | hits for the three canonical queries with backend and limit |
| `video/TT11-recall.mp4` | 30 s–5 min: suite, FTS group, fallback group, syntax-safety group |

## Oracles exercised

OR-07 (limit), N5 (graceful degradation), plan §13.1 (FTS gap).

## Done when

- `pytest tests/test_recall.py -q` green on all three OSes, including the
  monkeypatched fallback path.
- No test asserts on FTS ranking order beyond the top-3 sanity check.
- `docs/test-reports/TT11/` holds `test-report.md`, `pytest.log`,
  every screenshot embedded in the report, and the `video/TT11-recall.mp4`
  recording.
