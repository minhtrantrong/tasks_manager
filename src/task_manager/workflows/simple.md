---
name: simple
description: Single-session change, default workflow
lease_minutes: 30
---
You are working on task {title} (#{id}) in project {project}.

1. Re-read the task description through `task_get`.
2. Write a journal `note` describing the plan you are about to follow.
3. Make the change in one sitting; keep the diff focused on the task.
4. Verify the change with the smallest command that proves it.
5. Record a journal `result`, then `task_complete` with an outcome that says
   what changed and how you verified it.

If the task turns out bigger than one session, stop and ask for it to be split
into smaller tasks instead of growing this one.
