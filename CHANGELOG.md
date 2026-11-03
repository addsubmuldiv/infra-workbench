# Changelog

## 0.1.1 — 2026-11-03

- Windows desktop updater with quiet startup checks and manual check/download/install controls.
- Cryptographically signed update packages and version-bound signatures; public GitHub Release latest.json feed.
- Progress, release notes and retry, with native confirmation before installation.
- All-window unsaved-work checks, backend activity/drain protection and recovery on failed installer launch.
- Browser, demo, development and macOS builds do not run the Windows automatic installer.

Existing 0.1.0 users must manually install this bootstrap version once. Save work and exit the old tray/backend before installation. Future releases can use the updater after the repository is public. Signing keys are private; updater signing does not provide Windows Authenticode signing.

## 0.1.0 — 2026-11-03

Initial Windows x64 release of Infra Workbench.

- GPU and Ascend NPU resource overview, process inspection and idle-device alerts over SSH.
- Integrated terminals, file management, training-log comparison, AI assistant, MCP and Skills.
- Isolated browser demo with synthetic hosts and a spotlight onboarding guide.
- Bundled Python backend and NSIS setup wizard; the application footer displays v0.1.0.

The Windows installer is unsigned. Clean Windows install/upgrade/uninstall and native macOS acceptance remain pending. This release includes no macOS installer. Read SECURITY.md before enabling remote command or credential access.
