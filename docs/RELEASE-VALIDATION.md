# Desktop release validation

Validation date: 2026-11-03. These results describe this working tree and local Windows host, not a clean Windows or macOS installation.

## Release procedure

1. Update frontend/package.json, frontend/package-lock.json, desktop/package.json, desktop/package-lock.json, desktop/src-tauri/tauri.conf.json, desktop/src-tauri/Cargo.toml, and desktop/src-tauri/Cargo.lock together. Keep the backend /api/health version aligned. The application footer reads its version from the frontend package at build time.
2. Push a version tag such as v0.1.0, or manually run **Desktop release** with that existing tag. The tag must point to the checked-out commit and match the desktop versions.
3. The reusable desktop workflow builds Windows x64 by default; include_macos enables experimental Apple Silicon and Intel packages. Packaging runs the frozen Python runtime self-test, Rust tests, frontend tests, and WebKit checks. Missing installers fail artifact upload.
4. The release job requires signed artifacts for the selected platforms, writes latest.json and SHA256SUMS.txt, and creates a **draft** GitHub release. Only this job has contents: write; checkout does not persist credentials. Existing releases and their assets are preserved; the job skips creation when that tag already has a release.
5. Before publishing, download and verify all packages, complete the installation checks below, and inspect the workflow logs. GitHub workflows have not been executed in this local session.

Checksums detect corrupted downloads; they do not replace publisher signatures. The workflow provides neither Windows code signing nor macOS signing/notarization. Release notes explicitly disclose this.

## Locally verified

- node --test desktop/release.test.mjs: 2 tests passed (version mismatch/tag validation, required installer set and SHA256 known-answer check).
- cargo test --locked in desktop/src-tauri: 8 tests passed.
- Both workflow YAML files parsed with local PyYAML. This checks syntax, not GitHub execution or hosted-runner availability.
- NSIS uses a per-user installation (currentUser). Runtime packaging explicitly includes code/assets and runs a frozen-runtime self-test before bundling.

## Installation checks still required

- Clean Windows account or VM without Python, Node.js, or Rust: install, launch from Start menu, configure a machine, exercise terminal/file access, quit/relaunch, upgrade, uninstall. Test the WebView2 bootstrap installation path without an existing WebView2 runtime. Verify user configuration survives upgrade.
- Real Apple Silicon and Intel Macs: mount DMG, install into Applications, launch, exercise terminal/file access, quit/relaunch, upgrade, uninstall. Record Gatekeeper prompts and the unsigned/not-notarized distribution limitation.
- Check credentials and user data are absent from installers; confirm first-launch state and guidance. Test non-ASCII Windows user profiles and paths containing spaces.

Do not mark platform installation checks as passed based only on CI compilation or a frozen-runtime self-test.

## Initial local packaging attempt

The frontend production build and frozen Windows runtime self-test succeeded. The fresh receipt reported ok=true, frozen=true, native_pty=true, 12 built-in skills, and hosts=0. PyInstaller emitted optional-module/platform-DLL warnings; these are retained in work/release-validation/desktop-build.log and do not establish clean-machine compatibility.

The first Tauri build failed because a running desktop process locked target/release/infra-workbench-desktop.exe (Windows access denied). No running desktop process was terminated. Subsequent packaging uses an isolated CARGO_TARGET_DIR to avoid interfering with the user's open desktop window.

## Final Windows package

After the final frontend compatibility fixes, the Windows runtime was rebuilt and its new self-test receipt passed (ok=true, frozen=true, native_pty=true, hosts=0). Tauri NSIS packaging then completed with exit code 0 using the isolated target directory. The existing desktop process was left running.

- Installer: release/Infra-Workbench-0.1.0-windows-x64-setup.exe
- Size: 87,673,448 bytes (83.61 MiB)
- SHA256: 6944539bace944452af5341feaf4acdbc428789fdb1ed7f3afb54d2612623aa2
- Checksums: release/SHA256SUMS.txt
- Final v0.1.0 build log: work/release-validation/v010-build.log
- Self-test receipt: work/desktop-build/runtime-self-test.json

Reproduce packaging from the project root using the existing build environment:

```powershell
# npm run build in desktop normally builds frontend, runtime and NSIS together.
# Close an existing development executable first, or isolate Cargo output:
$env:CARGO_TARGET_DIR = Join-Path (Get-Location) 'work/release-validation/target'
Push-Location desktop
npm run build
Pop-Location
Copy-Item -LiteralPath 'work/release-validation/target/release/bundle/nsis/Infra Workbench_0.1.0_x64-setup.exe' -Destination 'release/Infra-Workbench-0.1.0-windows-x64-setup.exe'
Get-FileHash -LiteralPath 'release/Infra-Workbench-0.1.0-windows-x64-setup.exe' -Algorithm SHA256
```

The final local package has not been installed or upgraded in a clean Windows environment. macOS packages and the GitHub release workflow remain unexecuted in this session. No claim of completed clean-machine or macOS validation is made.

## v0.1.0 release preparation

The installer was rebuilt after adding the visible package-derived v0.1.0 footer. Frontend tests: 241 passed. Version/checksum tests: 2 passed. The frozen runtime self-test and NSIS packaging passed again. Chinese/English READMEs and CHANGELOG.md identify this first version. The tag and Release use the same source commit; only Windows x64 and the browser demo are attached. macOS and clean Windows acceptance remain pending.

## v0.1.1 signed updater validation

The Windows production build passed using an isolated Cargo target directory. The existing desktop and backend were left running. The frozen-runtime receipt reported ok=true, frozen=true, native_pty=true, hosts=0 and 12 built-in skills.

- Installer: release/v0.1.1/Infra-Workbench-0.1.1-windows-x86_64-setup.exe
- Size: 89,165,425 bytes (85.03 MiB)
- SHA256: 4bd0756f4074d0a813fca5ada2af6caf94b0779b72f876ba508b707c72057618
- Adjacent .sig, Windows-only latest.json and SHA256SUMS.txt are included.
- Installer payload signature, global signature and trusted version 0.1.1 were independently verified with the public key only.
- Backend: 685 passed, 11 skipped. Frontend: 249 passed and TypeScript passed. Native Rust: 13 passed, including real updater downloads rejecting modified bytes, invalid signatures and mismatched signed versions. Release tooling: 5 passed.
- Headless Edge exercised the built settings UI with a synthetic native bridge: check, download progress and install action passed without page errors. No actual installation occurred.
- The exact CI Playwright/WebKit version passed the local normal and legacy compatibility smoke checks. Earlier hosted WebKit/macOS failures were inspected; no claim is made that hosted CI or macOS packaging now passes.

Clean-machine installation and a real end-to-end upgrade remain untested. Updater signatures authenticate update packages; the installer has no Windows Authenticode signature. Version 0.1.0 requires one manual bootstrap installation. The public update feed becomes accessible without credentials after the repository is made public. Signing builds require TAURI_SIGNING_PRIVATE_KEY; explicit unsigned development builds use IWB_UNSIGNED_BUILD=1 and cannot supply update artifacts. See UPDATES.md for key handling and release instructions.
