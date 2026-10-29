---
name: bugfix
description: Reproduce, fix, verify
lease_minutes: 60
---
You are fixing task {title} (#{id}) in project {project}.

1. Reproduce the bug first. Record the exact command and the observed failure
   as a journal `attempt`.
2. Form one hypothesis at a time and write a journal `decision` naming it.
3. Fix the smallest cause, not the symptom.
4. Re-run the reproduction and the surrounding tests; record them as a `result`.
5. `task_complete` with an outcome stating the root cause, the fix, and the
   verification command.

If a hypothesis fails, journal an `attempt` with the error and why it failed so
nobody retries it later.
