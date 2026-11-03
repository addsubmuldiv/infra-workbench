# Browser demo and guided tour

The demo reuses the workbench interface with four synthetic hosts. It never connects to SSH, the model provider, MCP, email or the real backend. The assistant uses labelled preset answers. The terminal accepts only a few simulated commands. Unsupported actions show a demo limitation; there is no backend fallback.

## Run

- Running workbench: open `http://127.0.0.1:8765/?demo=1`.
- Frontend only (Node.js required for development): `cd frontend`, `npm ci`, `npm run demo`. No Python, SSH or model key is needed.
- Static hosting: `npm run build:demo` creates `frontend/demo-dist`. Serve that directory over HTTP, including beneath a path prefix. This build always starts in demo mode, even without the query parameter. Do not open index.html using file://. The Browser demo workflow builds a downloadable static artifact. Website publication is opt-in through its manual publish input.

The normal application build retains the real workbench; `?demo=1` explicitly enters the isolated demo. Leaving it reloads the real entry point. The standalone demo's exit action returns to the repository page because that artifact has no real backend.

## What to try

Follow the spotlight guide, or skip it and explore. Filter GPU/NPU resources, open a busy device's process details, create an availability alert, inspect/edit `/demo/train.log`, and open the simulated terminal. Try `help`, `pwd`, `ls`, `cat train.log`, and `clear`. Open the assistant and choose a preset example.

A seeded alert waits for the busy GPU. **Finish demo training** frees its devices and creates one in-page event. User-created alerts retain their selected continuous-idle waiting time; choose zero minutes to see the result immediately. No desktop notification permission or email is requested. **Reset** discards all simulated changes and restarts the guide. Reloading also resets demo state.

The guide highlights the actual controls, leaves them clickable, and follows opened dialogs. Next/Back, Skip, replay, Escape, and Tab are supported. On a narrow screen, machine selection uses the mobile machine picker. The demo is not a simulation of every settings or precision-comparison API; those unsupported operations fail explicitly.

## Isolation checks

- Demo initialization runs before workspace loading; legacy browser preferences are neither imported nor removed.
- Workspace state, fake hosts, files, alerts and preset responses live only in memory.
- Application fetch calls are handled in memory; unrecognized endpoints and absolute URLs are denied. WebSocket, EventSource, XMLHttpRequest, WebTransport, RTCPeerConnection and sendBeacon do not connect to real services.
- Static JavaScript, CSS, fonts and images still load from the demo host. This is an application-level isolation boundary, not a browser sandbox against arbitrary third-party code or extensions.

Run `npm test` in frontend for demo transport, legacy-storage isolation and reservation-state regression checks. Browser verification should include the five-step tour, keyboard skip, booking dialogs, file editing, reset, a narrow viewport and a zero-API-request network trace.

## Verification in this change

On 2026-11-03, the frontend suite passed 241 tests and both the normal and standalone demo production builds completed. Browser checks covered desktop and 390px layouts, the five-step tour, an active-tour assistant response, process and reservation dialogs, zero-wait simulated alerts, sample log viewing, a simulated terminal, Escape/replay focus, and retained legacy browser preferences. The normal workbench `?demo=1` entry and standalone static entry both showed zero actual `/api` resource requests. Static demo HTML includes a `connect-src 'none'` policy.

These checks validate the simulated interface and isolation behavior. They do not validate real SSH commands, model replies, operating-system notifications, public hosting, or installation on clean systems. Desktop packaging and remaining platform checks are recorded separately in [release validation](RELEASE-VALIDATION.md).

## Optional public demo deployment

In the repository's Settings → Pages, select GitHub Actions as the source, then manually run **Browser demo** with **publish** enabled. The workflow uploads the standalone artifact and deploys it through the `github-pages` environment; the job exposes the resulting URL. Default runs only build the artifact. This change has not enabled Pages or deployed a public site.

The deployment configuration follows [GitHub's custom Pages workflow documentation](https://docs.github.com/en/pages/getting-started-with-github-pages/using-custom-workflows-with-github-pages). Repository settings and account eligibility must support Pages. The build retains relative static-asset URLs so it can run beneath the repository path, and the deployed artifact always starts in isolated demo mode.
