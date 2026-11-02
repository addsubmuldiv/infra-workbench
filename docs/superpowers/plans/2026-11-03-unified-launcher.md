# Unified Windows launcher implementation plan

Goal: One branded GUI executable, default browser or configurable desktop window, common tray service and floating monitor enabled by default. Normal launch never opens a console; first install may show dependency installation.

- [ ] Tests for mode persistence/defaults, desktop availability, API validation, and mutually exclusive UI dispatch.
- [ ] Implement launcher service and protected startup settings routes; add settings UI with browser/desktop choice and float toggle.
- [ ] Build a native Windows GUI bootstrap with embedded existing Workbench icon. Check dependency stamp without a console; run installer visibly only when necessary.
- [ ] Replace old public CMD entrypoints with the unified executable, update installation/shortcut/docs and release flow; retain internal diagnostic scripts.
- [ ] Verify unit tests/frontend build, real no-console browser launch, desktop launch and visible native float without changing user data.
