# Windows startup validation

The frozen Python `--self-test` verifies imports, HTTP, frontend bytes and native
PTY support. It does not verify the native bootstrap's CSP or rendered layout.
On Windows it also acquires a local SSPI credential handle (without a token
exchange or server connection), exercising AsyncSSH's lazy pywin32 timezone
dependency. Missing `win32timezone` must fail the frozen runtime self-test.
Feature checks also cover password/key SSH and SFTP round trips against a
temporary loopback server, encrypted OpenSSH key import/export (bcrypt), Excel
template parsing, an assistant graph turn with an in-memory provider, CA data,
timezones, remote probe source files, theme/icon assets and Windows Tk/Pillow.
They use synthetic data and do not contact real SSH/model services or user agents.

The build copies the frozen runtime to a temporary path containing spaces and
Chinese characters, runs it outside the checkout with a system-only PATH, and
removes Python/Tcl development environment overrides. This catches dependencies
accidentally supplied by the build machine. The receipt is written to
`work/desktop-build/runtime-self-test.json`. These checks do not replace clean
Windows installation/upgrade/uninstall testing or real server/network checks.
Before publishing a desktop UI change, run both checks.

From `desktop/src-tauri`, run:

```powershell
cargo test --lib --bin infra-workbench-desktop
cargo run --release --example startup_validation -- C:\Temp\iwb-startup.json --auto-close
```

The native example embeds the same bootstrap and uses the production CSP. It
does not start, stop or connect to a backend. It checks the real WebView layout
and CSP violations, writes a JSON receipt, then exits with status 0 only when
the panel fits and the icon is 48 by 48 pixels. Omit `--auto-close` to inspect
the window manually. Its fixed 5% state is a test fixture, not backend progress.

Also test the installed application's normal launch with no existing backend.
On Windows the startup probe queries IPv4/IPv6 listener tables before HTTP so
loopback connection-refusal delays cannot prevent launching the bundled runtime.
Listener-table failures remain unknown; they do not prove service absence. A confirmed listener
whose HTTP health check times out must not cause a second backend to be started.
`startup.log` and the backend's `desktop.log` are stored in the application's
data directory (`%LOCALAPPDATA%\InfraWorkbench` by default).
