# User skills implementation plan

Goal: Deliver the approved chat-created and imported user skill system in an isolated worktree, without changing main.
Architecture: SkillService/SkillRegistry share transactional SQLite persistence, immutable versions, drafts and bounded package files. HTTP and MCP share services; Deep Agents consumes a per-turn virtual snapshot.
Execution: superpowers:subagent-driven-development for independent implementation tasks, followed by integration and whole-branch review. User has explicitly authorized full implementation; no additional design approval is needed.

## Tasks
- [ ] Backend core: backend/skill_service.py, backend/skill_routes.py, tests/test_user_skills.py. SQLite through existing Store; strict path/YAML/ZIP limits, draft revision validation, immutable installed versions, optimistic concurrency, builtin conflicts, rollback, import/export; APIs under /api/skills.
- [ ] Integration: backend/mcp_skills.py, backend/mcp_service.py, backend/agent_runtime.py, backend/agent_chat.py, backend/app.py. One registry for MCP and virtual files, management MCP tools, authoring instructions, next-turn snapshots removing stale files, explicit per-message selected skill, skill read/version receipts.
- [ ] Frontend: frontend/src/SkillsSettings.tsx, skills.ts/css, SettingsPage.tsx, AssistantChat.tsx, agentChat.ts. Management list/detail/import/editor/versions/export/delete, chat skill selector and receipts/cards; frontend tests.
- [ ] Validate and document: lifecycle/API/MCP/real framework tests, frontend tests/build, dependency checks, whole diff review. Commit on codex/user-skills, leave unmerged.

## Fixed interfaces
SkillService(store, builtin_root=None), catalog()->list metadata, read(name, version=None)->detail, snapshot()->(files, receipts), create_draft(files:dict[str,str], skill_name=None, base_version=None)->draft, update_draft(draft_id, revision, files)->draft, validate_draft(draft_id, revision, tools:list[str])->report, install_draft(draft_id, revision, tools:list[str])->result, set_enabled(name, enabled, expected_version)->result, rollback(name, version, expected_version)->result, delete(name, expected_version), import_package(filename, content:bytes)->draft, export(name, version=None)->bytes. Draft detail includes id, revision, files, skill_name, base_version; metadata includes name, description, source, enabled, version, warnings. snapshot files are plain UTF-8 strings under /skills/<name>/...; receipts list name/version/source.
HTTP: GET /api/skills -> {items}; GET /api/skills/{name}?version=; POST /api/skills/drafts {files,skill_name?,base_version?}; GET/PUT /api/skills/drafts/{id}; POST .../{id}/validate or /install {revision}; POST /api/skills/import?filename= raw bytes; PUT /api/skills/{name}/enabled {enabled,expected_version}; POST .../rollback {version,expected_version}; DELETE ...?expected_version=; GET .../export?version=. Errors 400/404/409 with readable detail. Detail files text, versions metadata list.
Limits: 2 MiB compressed upload, 8 MiB total expanded, 128 files, 1 MiB/file. Preserve binary assets via encoded package storage if needed, do not expose non-text to model; scripts inert. No symlinks/traversal/case collisions. Standard name max64, description max1024. Builtins immutable.

## Review focus
Uninstall/reinstall stale drafts and historical virtual files; concurrent edit/install; ZIP bomb/Windows paths/symlink/duplicate entries; dynamic MCP tool availability; no credentials or expanded host permissions. Static validation is not successful execution. Keep chat history, do not erase evidence.
