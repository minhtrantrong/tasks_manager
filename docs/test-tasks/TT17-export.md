# TT17 — Markdown and EDNL export

| | |
|---|---|
| Suite | `EXP` |
| Verifies | [T17](../tasks/T17-export.md) |
| Phase | M5 |
| Depends on | TT09 |
| Unblocks | — |
| Level | L2 |
| Size | S |
| Status | pending |

## Goal

Prove a human can review a project's full history as plain text, and that export
provably does not write.

## Files

- `tests/test_export.py` — new.

## Cases

1. Seeded project → Markdown contains every task title, every journal body, every
   block reason, and one relation line per edge.
2. EDNL round-trip: parse the emitted lines and assert every task, journal entry,
   relation, and context entry in the DB is represented exactly once.
3. Determinism: two consecutive exports are byte-identical, including with a frozen
   clock and tasks sharing a timestamp.
4. `path=` writes UTF-8 (non-ASCII title and journal body survive a read-back);
   the DB row counts and `updated_at` values are unchanged afterwards.
5. Story context appears under its story task only; children do not duplicate it.
6. Empty project exports a valid document with a header and no rows.
7. An unknown project raises `NotFound` and writes no file.
8. Export never emits an external URL and never opens a socket (N1/N8 guard).

## Test environment

| | |
|---|---|
| Surface | Terminal CLI (`pytest`); no server, no browser |
| Command | `python -m pytest tests/test_export.py -v` |
| Setup | `python -m pip install -e ".[dev]"` |
| Env | `TASKS_DB=<repo>\.tmp-tt17\tasks.sqlite`; frozen clock for determinism |
| Prereqs | CPython 3.12; a writable `tmp_path` for the `path=` cases |

## Test data

- Seeded project with tasks in several statuses, one blocked task with a reason,
  one edge of each relation kind, journal entries, and story context on a story
  with a child.
- Non-ASCII fixture: title `"Sửa lỗi bộ nạp plugin — 日本語"` and a journal body
  containing `"café ☕ — ñ"`, used for the UTF-8 read-back.
- Determinism fixture: tasks sharing one `created_at` under a frozen clock.
- Empty project `blank` with no tasks.
- Unknown slug `"nope"` for the no-file assertion.
- `path=` targets: `tmp_path/export.md` and `tmp_path/export.ednl`.

## How to test

1. `python -m pytest tests/test_export.py -v` with the recorder running.
2. Run the Markdown group — `-k "markdown or context or empty"` — and copy a
   rendered document into `attachments/export.md`.
3. Run the EDNL group — `-k "ednl or determinis"` — and copy the emitted lines into
   `attachments/export.ednl`; confirm two runs are byte-identical
   (`Get-FileHash` / `sha256sum`).
4. Run `-k "utf8 or read_only or unknown"` and screenshot the UTF-8 read-back and
   the unchanged row counts before/after export.
5. Record the network guard result (no socket opened) in the report.

## Expected results

| Case | Expectation |
|---|---|
| 1 | the Markdown contains every task title, journal body, block reason and one relation line per edge |
| 2 | every task, journal entry, relation and context entry appears exactly once in the EDNL output |
| 3 | two consecutive exports are byte-identical, including with equal timestamps |
| 4 | `path=` writes UTF-8 and the non-ASCII text survives a read-back; row counts and `updated_at` are unchanged |
| 5 | story context appears under its story only; children do not duplicate it |
| 6 | an empty project exports a valid document with a header and no rows |
| 7 | an unknown project raises `NotFound` and writes no file |
| 8 | export emits no external URL and opens no socket |

## Test artifacts

Folder `docs/test-reports/TT17/` — layout and capture commands in
[test-reports/README.md](../test-reports/README.md).

| Path | Must show |
|---|---|
| `test-report.md` | verdict, 8 case rows, hashes of the two export runs, embedded screenshots, video link |
| `pytest.log` | full run plus the Markdown, EDNL and UTF-8 selections |
| `screenshots/01-markdown-export.png` | the rendered Markdown with tasks, journal, reasons and edges |
| `screenshots/02-ednl-round-trip.png` | the EDNL lines and the exact-once assertions |
| `screenshots/03-utf8-readback.png` | the non-ASCII title/body after reading back the written file |
| `attachments/export.md` | full Markdown export used in cases 1 and 5 |
| `attachments/export.ednl` | full EDNL export used in case 2 |
| `video/TT17-export.mp4` | 30 s–5 min: suite, Markdown export, EDNL determinism, UTF-8 read-back |

## Oracles exercised

OR-01 (read-only), OR-08, Q6 (export on demand, no mirror).

## Done when

- `pytest tests/test_export.py -q` green on all three OSes.
- Case 3 fails if dict ordering or timestamps are non-deterministic.
- `docs/test-reports/TT17/` holds `test-report.md`, `pytest.log`,
  every screenshot embedded in the report, and the `video/TT17-export.mp4`
  recording.
