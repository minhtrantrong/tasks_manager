---
name: spike
description: Time-boxed exploration, write up findings
lease_minutes: 120
---
This is a spike: task {title} (#{id}) in project {project}.

1. Write down the question the spike must answer in a journal `note` before
   exploring.
2. Time-box the exploration; stop when the lease is half gone.
3. Record each dead end as a journal `attempt` with the reason it failed.
4. Produce a written finding: what you learned, what you would build next, and
   the risks you found. Put it in `context_append` so sibling tasks inherit it.
5. `task_complete` with an outcome that points at the finding.

A spike produces knowledge, not production code. Do not merge throwaway code
into the main path.
