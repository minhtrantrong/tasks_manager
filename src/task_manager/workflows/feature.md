---
name: feature
description: Ship a feature end-to-end with tests
lease_minutes: 90
---
You are shipping task {title} (#{id}) in project {project}.

1. Design first: write a journal `decision` with the chosen shape and the
   alternatives you rejected.
2. Implement the smallest vertical slice that proves the design.
3. Add tests for the behaviour, not the implementation.
4. Update the documentation that describes the changed behaviour.
5. Record a journal `result` with the verification commands and outcomes, then
   `task_complete`.

If the work spans more than one session, checkpoint before you stop and leave
concrete `next_actions` rather than a prose summary.
