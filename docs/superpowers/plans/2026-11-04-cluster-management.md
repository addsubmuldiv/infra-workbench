# Cluster Management Implementation Plan

> Use superpowers:subagent-driven-development to implement and review tasks.

Goal: Deliver approved cluster grouping, batch terminal and command execution in UI and MCP.
Architecture: Persistent cluster service and batch scheduler reuse single-host command execution. HTTP and MCP share scope-checked services; React provides grouped sidebar and workspace.
Tech Stack: Python, SQLite, FastAPI, React, TypeScript.
Spec: docs/superpowers/specs/2026-11-03-cluster-management-design.md

## Constraints and review focus
- Preserve unrelated floating-window changes; do not push or restart live services.
- One cluster per host, optimistic revision, fixed batch targets, no automatic command retries.
- Scope-limited MCP must not leak or modify hidden members.
- Unknown launches must recover with a preallocated job ID; no duplicate launch after restart.
- Terminal broadcast requires verified shell readiness, never writes into busy sessions.

## Tasks
- [x] Backend: backend/clusters.py and cluster routes, persisted cluster/member and batch records, command jobs with injected IDs; tests/test_clusters.py verifies revisions, scopes, identity, duplicate requests, recovery, cancellation and partial failure.
- [x] Frontend: frontend/src/ClusterPanel.tsx and cluster styles; main.tsx grouping and terminal workspace integration; ServerImport.tsx target selector. Consume /api/clusters and /api/cluster-batches contracts; verify TypeScript, build and interaction tests.
- [x] Integration: MCP shared catalog and scope checks, import assignment and terminal sessions; targeted tests and docs.
- [x] Review complete diff for spec and correctness, fix findings; run relevant backend regression and frontend checks.

Ruling: Execute in current worktree on a codex feature branch to preserve visible uncommitted user changes; no automatic commits of unrelated files.
