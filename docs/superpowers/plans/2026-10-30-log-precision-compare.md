# Training precision comparison implementation plan

Execute in this chat without delegation. Branch: feature/log-precision-compare.

Goal: select two existing SSH machines and log paths, parse JSON iteration/loss/grad_norm without regex, align actual steps, show MAE/max error and curves, remember comparisons.

Architecture: standalone bounded read-only remote Python reader; backend snapshot cache and comparison functions; FastAPI routes registered separately; React precision page with SVG charts. Reuse existing SSH, themes, SQLite. No remote installation, sudo, new dependency, or alteration of existing monitoring/terminal behavior.

- [x] Write failing tests for prefixed JSON, scientific notation, iteration fractions, invalid numbers, ranks/restarts/duplicates, missing steps and hand-checkable MAE.
- [x] Implement backend/log_reader.py and backend/log_compare.py; bounded regular-file reads (64 MiB, 10,000 records, 64 KiB lines), explicit refusal on excess. Separate rank/segment, require selection when ambiguous, reject duplicates by default.
- [x] Write API tests for two hosts, paths with shell metacharacters, remote errors, stale snapshots, CSRF and saved configurations. Implement backend/log_routes.py and register from app.py. Paths travel only in Python stdin; finite cached results, no raw logs persisted.
- [x] Implement frontend/src/PrecisionCompare.tsx and precision.css. Inputs with remote browser, extraction preview/group selection, default loss/grad_norm, optional numeric fields, range/duplicate options, MAE/max/error-step, raw and error curves, row-to-source inspection and CSV export. Save named configs and browser draft.
- [x] Verify with controlled local remote-reader/API tests and browser example, build frontend, review changes locally, document usage and limits. Do not restart unrelated live monitoring or close SSH terminals without checking ownership and impact.

Acceptance: sample iteration 1/300 becomes step 1; base steps 1,2,4 versus test 1,3,4 compare only 1,4; duplicate/rank/restart ambiguity cannot silently select a trajectory; NaN/Infinity never contaminate summaries; no matching metric is explicit. Large files do not produce partial MAE. Snapshot refresh explicit; chart downsampling never changes summary statistics. Real server validation depends on user-provided log locations.
