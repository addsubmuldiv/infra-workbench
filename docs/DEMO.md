# Browser demo and guided tour

The demo reuses the workbench interface with four synthetic hosts. It never connects to SSH, the model provider, MCP, email or the real backend. The assistant uses labelled preset answers. The terminal accepts only a few simulated commands. Unsupported actions show a demo limitation; there is no backend fallback.

## Real first-run guide and demo tour

The normal workbench now has a separate six-step getting-started guide. It appears after the first successful load of a new empty workspace, remembers completion or skipping in shared workspace state, and can be replayed from **Settings → About and help → Replay getting-started guide**. It introduces connections, aliases/clusters, terminals/files/tunnels/VS Code, AI engines and scope, alerts/history, and settings. Existing workspaces with hosts are not forced through it on upgrade. See the [user guide](GUIDE.en.md#first-use-and-getting-started-guide).

The nine-step spotlight tour below belongs to the isolated demo. Completing or skipping that tour does not mark the real-workspace guide complete. Newer real features such as cluster batch operations, persistent SSH tunnels, local CLI engines, and durable resource history are described where helpful, but are not presented as supported demo actions. Real credentials and server operations must be configured after exiting demo.

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

Run `npm test` in frontend for demo transport, legacy-storage isolation and reservation-state regression checks. Browser verification should include the nine-step tour, keyboard skip, booking dialogs, file editing, reset, a narrow viewport and a zero-API-request network trace.

## Historical verification (2026-11-03)

On 2026-11-03, the frontend suite passed 241 tests and both the normal and standalone demo production builds completed. Browser checks covered desktop and 390px layouts, the five-step tour, an active-tour assistant response, process and reservation dialogs, zero-wait simulated alerts, sample log viewing, a simulated terminal, Escape/replay focus, and retained legacy browser preferences. The normal workbench `?demo=1` entry and standalone static entry both showed zero actual `/api` resource requests. Static demo HTML includes a `connect-src 'none'` policy.

These checks validate the simulated interface and isolation behavior. They do not validate real SSH commands, model replies, operating-system notifications, public hosting, or installation on clean systems. Desktop packaging and remaining platform checks are recorded separately in [release validation](RELEASE-VALIDATION.md).

## Optional public demo deployment

In the repository's Settings → Pages, select GitHub Actions as the source, then manually run **Browser demo** with **publish** enabled. The workflow uploads the standalone artifact and deploys it through the `github-pages` environment; the job exposes the resulting URL. Default runs only build the artifact. This change has not enabled Pages or deployed a public site.

The deployment configuration follows [GitHub's custom Pages workflow documentation](https://docs.github.com/en/pages/getting-started-with-github-pages/using-custom-workflows-with-github-pages). Repository settings and account eligibility must support Pages. The build retains relative static-asset URLs so it can run beneath the repository path, and the deployed artifact always starts in isolated demo mode.

## Nine-step demo tour

The guide now follows the first-use workflow: resource overview → host selection → idle-device filtering → process inspection → availability alerts → files and sample logs → terminal → AI assistant → setup and Skills/MCP entry points. The selected steps introduce the main day-to-day operations without visiting unsupported demo screens.

Changing steps closes the previous demo dialog or floating window and restores the overview so the next control stays reachable. Save edits before continuing. The availability-alert step includes a simulated training-completion button. Guide cards measure their rendered height to stay within narrow viewports.

Validation for this update: TypeScript check, 241 frontend tests, an isolated standalone production build, all nine desktop steps including live simulated controls, and all nine cards at a 390px viewport. The browser recorded no real `/api` requests during the tour. The published installer was not rebuilt as part of this guide-only update.
