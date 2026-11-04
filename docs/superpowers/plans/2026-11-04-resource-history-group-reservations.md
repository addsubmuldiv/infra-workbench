# Resource history and group reservations implementation

Approved design: ../specs/2026-11-04-cluster-reservations-resource-history-design.md, including latest UI revisions. Execute first-version scope; no changes to real host configuration or real reservations during tests. Retain earlier uncommitted fixes. Work branch: codex/resource-history-group-reservations.

## Tasks

1. History backend (`backend/resource_stats.py`, `backend/resource_stats_routes.py`, tests): write failing tests for observation expiry, failure, restart, partial unknown, time integration, identity changes and local day boundaries. Implement durable bounded 30-day data, half-open segments and quantity/coverage summaries. Public `ResourceStats(store)`, `observe(host,snapshot,collection_started_at=None,now=None,refresh_interval=10)`, `close(now=None)`, `register_resource_history_routes(app, service, hosts)`. GET `/api/resource-history?host_ids=<comma-separated>&date=YYYY-MM-DD&timezone=...&kind=GPU|NPU`. Return explicit segments and unknowns. Verify tests.
2. Group backend (`backend/group_reservations.py`, `backend/group_reservation_routes.py`, mail/link integration, tests): failing tests for specified/all vs any-N, freshness including collection time, post-creation evidence, reset/expiry/member replacement, revisions, restart and notification idempotency. `GroupReservationService(store,hosts,snapshots,clusters,mail)`, `observe(host_id,now=None)` and `tick(now=None)`; register routes separately. Durable config is acceptable to reuse atomic outbox transaction safely, rather than adding another independently committed table. No app.py edits by worker.
3. History frontend (`frontend/src/ResourceHistory.tsx`, `resourceHistory.css`, helpers/tests): API contract coordinated with history backend. Date, target, type, timezone; actual single-day quantity chart and cluster mutually-exclusive stacked machine chart plus heatmap; 0/unknown distinct, no reservation thresholds. Flat translucent tint, fine outline, small rounded segments; unit labels and accessible data table. Component `ResourceHistory({hosts,initialHostIds?})`. No main/navigation edits by worker.
4. Root integration and group frontend (`GroupReservations.tsx/css`, main/navigation/ClusterSidebar, app.py): hook success/failure observations and collector start time, lifespan expiration job and history run close; reservation list/dialog supports shared numeric per-host conditions, cluster membership snapshot, edit/cancel/rebook/notification deep link; keep single-machine UI intact. History/booking entrypoints from scope/cluster. Update documentation and labels.
5. Verify integration with backend tests, frontend node tests and TypeScript production build; inspect final diff and independent review for freshness/unknown accounting/duplicate notifications/authorization. Fix findings, report limitations of native UI and live-network validation honestly. Do not deploy, push, or create user reservations.

## Review focus

- Samples cannot be extended across expiry, failure, restart or missing writes; today future excluded.
- Any-N continues with sufficient known candidates despite unrelated failures; specified targets all required; fresh evidence after creation.
- Completed state and one notification commit together; edit/cancel cannot replay old notification.
- GPU/NPU and device identity remain separate; unknown is never zero idle; no fake historical backfill.
- API validation, local write header, target scope, date ranges, and group notification routing are preserved.

## Progress

- Plan prepared; parallel ownership explicitly separated. Implementation in progress.
- Ruling: retain the existing dirty worktree on a new branch rather than moving user/session changes to a second checkout; this keeps the running source context coherent and avoids losing the approved design.
- Ruling: synchronous short SQLite batches are acceptable initially if measured and bounded; dropped/failed samples must still create an explicit unknown boundary. Do not introduce unbounded queues.

- Tasks 1–4 implemented: durable history, group reservation state machine/outbox, real API-connected UI, navigation and runtime lifecycle.
- Review fixes: off-loop bounded readonly queries; lossless identical payload spans with per-sample evidence; repeating bounded independent-connection cleanup; clock rollback quarantine; mandatory PATCH version; visible mail receipts; cleanup cancellation preserves shutdown.
- Integration: synthetic app tests cover collection→history and group qualification→one outbox/deeplink, storage-error isolation and shutdown cleanup failure.
- Frontend: 300 tests pass; final production build in progress at this entry. Full tests/ backend suite running (exclude unrelated archived work/ copies and diagnostic entrypoint scripts).
- Deferred by approved first-version scope: CSV export, adjustable retention/7-day overview, per-host heterogeneous group conditions and AI/MCP extensions. No deployment, push, or real user reservation created.

- Final verification: backend `python -m pytest tests -q` => 848 passed, 11 skipped; frontend `npm test` => 300 passed; TypeScript + Vite production build succeeded (existing chunk-size warnings).
- Browser smoke: real history component rendered using an isolated mocked history API response; four heatmap intervals and 7px individual cell radii verified. No real reservation, remote modification, or backend restart performed. Browser test session closed.
- Completed first-version scope; current running backend needs restart before new endpoints and new history recording are active. Long-duration real-machine history accumulation remains operational validation, not fabricated test data.
