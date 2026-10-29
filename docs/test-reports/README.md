# Test evidence and artifacts

Every test task `TTxx` records its run in **one folder per test task**:

```
docs/test-reports/<Test-ID>/
```

`<Test-ID>` is the test task id (`TT00` … `TT23`). A test task is `done` only when
its folder exists, is complete, and holds evidence that matches the run described
in its `test-report.md`. Reports are committed with the run that produced them;
they are never written retroactively from memory.

## 1. Folder layout

```
docs/test-reports/TT20/
  test-report.md                 # required — the report (template in §5)
  pytest.log                     # required — verbatim pytest output of the recorded run
  screenshots/
    01-board-default.png         # required — every screenshot is embedded in the report
    02-waiting-badge.png
    03-lease-countdown.png
    04-show-cancelled.png
  video/
    TT20-board.mp4               # required — screen recording of the same steps
  attachments/                   # optional — evidence that is not a screen
    board.html                   #   rendered HTML, JSON payloads, db dumps, wheel listing
    api-headers.txt
```

Rules:

1. **One folder per test task.** No `TT20-…` sub-folders, no shared folder for two
   test ids. A re-run replaces the contents of the folder and bumps `run` in the
   report; it does not append a second `test-report-2.md`.
2. **No run residue.** Do not commit `__pycache__/`, `.pytest_cache/`, the SQLite
   file used by the run, or `tmp_path` copies. `attachments/` holds only files a
   reviewer needs to re-check a claim.
3. **Names are stable and sortable.**

   | Kind | Pattern | Example |
   |---|---|---|
   | Report | `test-report.md` | `test-report.md` |
   | Test log | `pytest.log` | `pytest.log` |
   | Screenshot | `NN-<slug>.png` (`NN` = 01…99, execution order) | `03-cycle-rejected.png` |
   | Video | `<Test-ID>-<slug>.mp4` | `TT05-relations.mp4` |
   | Second video | `<Test-ID>-<slug>-2.mp4` | `TT21-board-walk-2.mp4` |
   | Attachment | `<purpose>.<ext>` | `seed-parity-snapshot.sql` |

   Slugs are lower-case kebab-case and describe what the evidence proves, not the
   tool that produced it.

4. **Redaction.** No credentials, tokens, absolute home paths containing a user
   name, or unrelated windows in a screenshot or video.

## 2. Screenshots — capture and insert

Every test task captures at least one screenshot per case group, and **every
screenshot in `screenshots/` is embedded in `test-report.md`** with a caption that
names the case and the claim it proves. A screenshot that is not embedded is not
evidence.

| Surface under test | Capture method |
|---|---|
| Terminal (CLI, pytest, packaging) | OS capture, saved straight into `screenshots/`:<br>Windows `Win+Shift+S` → save as PNG<br>macOS `Cmd+Shift+4`<br>Linux `gnome-screenshot -f docs/test-reports/TT02/screenshots/01-pragmas.png` |
| Dashboard page (`L4`) | Headless browser, deterministic viewport 1600×1000:<br>Windows `& "C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe" --headless=new --disable-gpu --window-size=1600,1000 --screenshot="docs/test-reports/TT20/screenshots/01-board-default.png" http://127.0.0.1:8765/board`<br>macOS `"/Applications/Google Chrome.app/Contents/MacOS/Google Chrome" --headless=new --window-size=1600,1000 --screenshot=...`<br>Linux `chromium --headless=new --window-size=1600,1000 --screenshot=...` |
| HTTP / JSON payloads | `curl -s -D attachments/api-headers.txt http://127.0.0.1:8765/health`, then screenshot the terminal (status line + body visible) and keep the headers file |
| Test-run summary | Screenshot the pytest summary line **and** the per-case list, so the report can be checked against `pytest.log` |

Insertion pattern used in every report:

```markdown
### TT20/3 — dependent card carries a `waits #<id>` badge
![Board showing waits badge and dimmed card](./screenshots/02-waiting-badge.png)
```

Alt text repeats the claim; the caption below the image names the case id.

## 3. Video — one recording per test task

Each test task produces one screen recording of the same steps listed under *How to
test*, ending on the pass/fail summary.

| Surface | Capture method |
|---|---|
| Desktop / browser | Windows `Win+Alt+R` (Game Bar, saves MP4 to `Videos\Captures`) or OBS Studio; macOS `Shift+Cmd+5`; Linux `ffmpeg -f x11grab -framerate 15 -video_size 1920x1080 -i :0.0 -t 300 -pix_fmt yuv420p video/TT20-board.mp4` |
| Single window | Windows Game Bar *Record window*; macOS QuickTime *New Screen Recording*; Linux `ffmpeg -f x11grab -video_size …` on the window geometry |
| Terminal only (optional, small) | `asciinema rec video/TT01.cast` then `agg video/TT01.cast video/TT01-smoke-cli.mp4` |

Rules:

1. Length 30 s – 5 min. Longer evidence is split into numbered videos.
2. The recording shows the commands/pages from *How to test* in order — a viewer
   must be able to follow the run without the report open.
3. End on the verdict: the pytest summary line, or the final board state for `L4`
   tasks.
4. File `video/<Test-ID>-<slug>.mp4` (`.mkv`/`.webm` accepted when the OS recorder
   cannot emit MP4). Commit when ≤20 MB; above that, keep the file out of Git,
   attach it to the PR, and link the location from the report's *Video* section.

## 4. Capturing the test run

```powershell
# PowerShell — Windows
New-Item -ItemType Directory -Force docs/test-reports/TT02/screenshots, docs/test-reports/TT02/video | Out-Null
$env:TASKS_DB = "$PWD\.tmp-tt02\tasks.sqlite"
python -m pytest tests/test_db.py -v 2>&1 | Tee-Object docs/test-reports/TT02/pytest.log
Remove-Item Env:\TASKS_DB
```

```bash
# bash — macOS / Linux
mkdir -p docs/test-reports/TT02/screenshots docs/test-reports/TT02/video
TASKS_DB="$PWD/.tmp-tt02/tasks.sqlite" python -m pytest tests/test_db.py -v 2>&1 | tee docs/test-reports/TT02/pytest.log
```

`pytest.log` must be the output of the run the report describes, including the
summary line (`14 passed in 3.42s`) and every skip reason.

## 5. `test-report.md` template

Copy this into `docs/test-reports/<Test-ID>/test-report.md` and fill every row.

```markdown
# <Test-ID> — <test task title>

| | |
|---|---|
| Test task | TT07 |
| Date | 2026-10-30 |
| Commit | 1a2b3c4 |
| OS / Python | Windows 11 23H2 / CPython 3.12.10 |
| Run | 1 |
| Verdict | PASS — 14/14 cases |

## Environment

- Surface: terminal CLI (`pytest`), no server
- Command: `python -m pytest tests/test_transitions.py -v`
- Env: `TASKS_DB=$PWD/.tmp-tt07/tasks.sqlite`, frozen clock fixture

## Results

| Case | Expectation | Result | Evidence |
|---|---|---|---|
| TT07/1 | every legal edge lands on the expected status/fields | PASS | `pytest.log` |
| TT07/2 | every absent (status, action) pair raises `IllegalTransition` | PASS | [02-illegal-matrix.png](./screenshots/02-illegal-matrix.png) |

## Screenshots

### TT07/2 — illegal (status, action) matrix rejected
![28 illegal pairs raise IllegalTransition](./screenshots/02-illegal-matrix.png)

## Video

[TT07 lifecycle walkthrough](./video/TT07-lifecycle-transitions.mp4) — 1:42, shows
add → start → block → unblock → start → complete → close and the FAIL→PASS rerun.

## Artifacts

| File | Purpose |
|---|---|
| `pytest.log` | full run output, summary line included |
| `attachments/journal-kinds.json` | dump used to check the `problem` mirror |

## Notes / defects

- none
```

## 6. Per-run checklist

- [ ] `test-report.md` present and every table row filled.
- [ ] `pytest.log` from the recorded run, summary line visible.
- [ ] At least one screenshot per case group, all embedded in the report.
- [ ] One video present, shows the documented steps, ends on the verdict.
- [ ] Report states OS, Python, commit, run number, and case counts.
- [ ] Folder contains no test residue (DB files, caches, `tmp_path` copies).
- [ ] Every failed case is summarised under *Notes / defects* with a severity
      (`S1`–`S4`, plan §12) and a link to the defect.
