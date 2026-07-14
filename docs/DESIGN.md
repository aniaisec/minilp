# DESIGN.md — Decision log

Filled in as milestones land. Planned sections:

- Counterbalancing: why pre-generated slots instead of per-render randomization (M1/M2)
- Slot leasing with `SELECT ... FOR UPDATE SKIP LOCKED` (M2)
- Role-gated auth (admin/reviewer/annotator via `users.role`) instead of a flat API-key — why roles were added before M7 landed judges, and why `annotators` stays separate from `users` (M1/M2)
- Reputation weighting (M4)
