# Browser demo and guided tour

The demo reuses the workbench interface with eight synthetic hosts across three clusters. The hosts include idle, busy, offline, and stale samples. All demo state stays in the page. The assistant uses labelled preset answers, and the terminal accepts a few simulated commands.

## Real first-run guide and demo tour

The normal workbench has a separate eight-step getting-started guide. It appears after the first successful load of a new empty workspace and remembers completion or skipping. Open **Settings → About and help → Replay getting-started guide** to see it again. It covers connecting a machine, resource filters, SSH accounts and process details, remote tools, AI, alerts and history, precision comparison, and settings. See the [user guide](GUIDE.en.md#first-use-and-getting-started-guide).

The isolated demo offers a 16-step interactive tour. Use the step selector to jump to a feature, or skip the tour and explore. Settings explain where to configure real SSH accounts, model providers, local CLI engines, Skills, MCP, email, and desktop features.

## Run

- Running workbench: open `http://127.0.0.1:8765/?demo=1`.
- Frontend only (Node.js required for development): `cd frontend`, `npm ci`, `npm run demo`. No Python, SSH or model key is needed.
- Static hosting: `npm run build:demo` creates `frontend/demo-dist`. Serve that directory over HTTP, including beneath a path prefix. This build always starts in demo mode, even without the query parameter. Do not open index.html using file://. The Browser demo workflow builds a downloadable static artifact. Website publication is opt-in through its manual publish input.

The normal application build retains the real workbench; `?demo=1` explicitly enters the isolated demo. Leaving it reloads the real entry point. The standalone demo's exit action returns to the repository page because that artifact has no real backend.

## What to try

Try GPU/NPU filters, cluster membership, process details, a training preflight check, and device monitoring. Resource history includes samples with collection gaps. The two precision logs share most steps and each has one unmatched step. Open the result to inspect source lines or export CSV.

Two sample alerts wait for the busy GPU machine. **Finish demo training** frees its devices and satisfies both the single-device and cluster alert once. Choose a zero-minute delay for a new alert to see the result immediately. The notification center receives the simulated events. **Reset** discards all simulated changes and restarts the tour.

Browse and edit sample files, try `cat train.log` in the terminal, and inspect a preset assistant reply and its tool record. The tunnel manager and Services simulate starting and stopping forwarding rules. The demo opens no listening ports or service URLs. Use the regular workbench for real SSH sessions, cluster commands, models, credentials, and integrations.

## Isolation checks

- Demo initialization runs before workspace loading; legacy browser preferences are neither imported nor removed.
- Workspace state, fake hosts, files, alerts and preset responses live only in memory.
- Application fetch calls are handled in memory; unrecognized endpoints and absolute URLs are denied. WebSocket, EventSource, XMLHttpRequest, WebTransport, RTCPeerConnection and sendBeacon do not connect to real services.
- In the desktop window, Tauri's native ready handshake and title bar controls keep working over its local IPC protocol. Workbench API requests continue to use the simulated transport.
- Static JavaScript, CSS, fonts and images still load from the demo host. This is an application-level isolation boundary, not a browser sandbox against arbitrary third-party code or extensions.

Run `python scripts/run_tests.py workspace desktop --scope frontend` for demo state, IPC, and network isolation regression checks. In the browser, verify entry from the first-run guide and settings, navigation through the 16 steps, reset and replay, and simulated actions.

## Historical verification (2026-11-03)

On 2026-11-03, the frontend suite passed 241 tests and both the normal and standalone demo production builds completed. Browser checks covered desktop and 390px layouts, the five-step tour, an active-tour assistant response, process and reservation dialogs, zero-wait simulated alerts, sample log viewing, a simulated terminal, Escape/replay focus, and retained legacy browser preferences. The normal workbench `?demo=1` entry and standalone static entry both showed zero actual `/api` resource requests. Static demo HTML includes a `connect-src 'none'` policy.

These checks validate the simulated interface and isolation behavior. They do not validate real SSH commands, model replies, operating-system notifications, public hosting, or installation on clean systems. Desktop packaging and remaining platform checks are recorded separately in [release validation](validation/RELEASE-VALIDATION.md).

## Optional public demo deployment

In the repository's Settings → Pages, select GitHub Actions as the source, then manually run **Browser demo** with **publish** enabled. The workflow uploads the standalone artifact and deploys it through the `github-pages` environment; the job exposes the resulting URL. Default runs only build the artifact. This change has not enabled Pages or deployed a public site.

The deployment configuration follows [GitHub's custom Pages workflow documentation](https://docs.github.com/en/pages/getting-started-with-github-pages/using-custom-workflows-with-github-pages). Repository settings and account eligibility must support Pages. The build retains relative static-asset URLs so it can run beneath the repository path, and the deployed artifact always starts in isolated demo mode.
