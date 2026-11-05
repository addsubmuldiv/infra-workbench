<p align="center">
  <img src="backend/assets/workbench.svg" alt="Infra Workbench Logo" width="96" height="96">
</p>
<h1 align="center">Infra Workbench</h1>

<p align="center">
  <a href="README.md">简体中文</a> | <a href="README.en.md">English</a>
</p>

**An AI-native server workbench for AI engineers.** Connect to multiple Linux servers over SSH and bring GPU / Ascend NPU discovery, process inspection, training logs, terminals, and file management into one workspace. Use the interface directly, ask the built-in AI assistant to call workbench tools, or connect your own agent through MCP.

Built for engineers training, fine-tuning, deploying, and debugging models across multiple machines: find enough free accelerators, identify the processes using them, open the right directory and terminal, get notified when resources become available, and compare training metrics across experiments. Windows is the primary platform; macOS support is available but has not been verified on physical Mac hardware.

![Resource overview with demonstration data](docs/images/overview-en.png)

*Screenshots use fictional machines and sample data. See the [illustrated user guide](docs/GUIDE.en.md). The interface supports Simplified Chinese and English. Switch under Settings → General → Interface language. The screenshots below show the English interface.*

## Desktop installation on Windows

Download the Windows x64 installer from the [latest Release](https://github.com/addsubmuldiv/infra-workbench/releases/latest), then follow its setup wizard. The installer bundles the Python backend and frontend assets; Python and Node.js do not need to be installed separately. Check download integrity using the attached `SHA256SUMS.txt`. This document describes the current repository; consult the relevant Release notes for features included in a published installer.

The Windows installer has no Authenticode code signature; updater packages carry a separate update signature. Clean Windows install, upgrade and uninstall acceptance is still pending. macOS packages must be built on a Mac; experimental Apple Silicon packages are included only when explicitly listed on the relevant Release. See [macOS installation and limitations](docs/MACOS.md), currently in Chinese; native Mac acceptance is still pending.

Developers can also extract the complete repository and run **`安装.cmd`** from source. This prepares Python and dependencies over the internet and requires keeping the whole project directory. See [Windows instructions](docs/WINDOWS.md).

A new empty workspace shows a six-step getting-started guide after its first successful load: connect hosts, inspect resources, use terminals and files, configure AI, plan availability, and find settings. Completing or skipping it is remembered. Upgrading a workspace with existing hosts does not force the guide open; replay it under **Settings → About and help → Replay getting-started guide**. See [first use](docs/GUIDE.en.md#first-use-and-getting-started-guide).

Desktop windows, the tray, and the floating monitor share the local backend. Use the tray menu to exit the backend.

Windows installers support startup update checks and user-initiated download/installation from v0.1.1. Existing v0.1.0 users must manually install this bootstrap version once; save work and exit the old tray/backend first. See [updater operation and limits](docs/UPDATES.md).

## First use

Choose **Add machine**, connect with your local SSH alias or address and account, then check sample time and devices before opening a terminal or files. Follow [Connect your first server](docs/GUIDE.en.md#connect-your-first-server) for expected results and recovery steps. Manual resource views, terminals and files require no model key; configure AI later using the [selection guide](docs/GUIDE.en.md#choose-how-to-use-ai).

## Browser demo

After starting the frontend or workbench locally, append `?demo=1` to its address, for example `http://127.0.0.1:8765/?demo=1`. Explore sample resources, terminals, files, and a highlighted walkthrough. The demo uses browser-only simulated data and isolates requests to the real backend. It does not connect to servers or model providers, and does not validate SSH, credentials, notifications, or installation. Simulated actions do not change the real workbench.

For a frontend-only demo, run `npm ci` and `npm run demo` in `frontend`; `npm run build:demo` creates a static artifact. See [demo isolation and limitations](docs/DEMO.md).

## Find documentation by task

| Task | Guide |
| --- | --- |
| Connect your first server and check results | [First connection](docs/GUIDE.en.md#connect-your-first-server) |
| Import hosts or organize clusters | [Import](docs/IMPORT.md) · [Clusters](docs/CLUSTERS.md) |
| Wait for devices or inspect usage history | [Alerts](docs/RESERVATIONS.md) · [History](docs/RESOURCE-HISTORY.md) |
| Use terminals and server files | [Terminals](docs/TERMINAL.md) · [Files](docs/FILES.md) |
| Open TensorBoard / Jupyter or VS Code | [Services](docs/PORT-FORWARDING.md#english) · [SSH tunnels](docs/SSH-TUNNELS.md#english) |
| Configure AI or reuse workflows | [Choose AI](docs/GUIDE.en.md#choose-how-to-use-ai) · [Skills](docs/USER-SKILLS.md) |
| Connect another AI client | [MCP](docs/MCP.md) |
| Receive notifications or use the monitor | [Email](docs/MAIL.md) · [Monitor](docs/FLOATING-MONITOR.en.md) |
| Compare training metrics | [Precision](docs/PRECISION.md) |
| Diagnose problems | [Troubleshooting](docs/TROUBLESHOOTING.md) |

The [full index](docs/README.md) and some detailed guides are currently in Chinese.

## Requirements, updates, and data

The local machine needs **Windows 10 / 11 and the OpenSSH client**. For source installation, if Python is missing, `安装.cmd` attempts to install Python 3.12 with WinGet; without WinGet, [install Python manually](https://www.python.org/downloads/windows/). Remote machines need Linux, Python 3, and `nvidia-smi` or `npu-smi`.

Jump hosts may run Windows or Linux and only need an SSH service which permits TCP forwarding. The app uses `ProxyJump` / `ProxyCommand` from the local SSH configuration without detecting the jump host's OS or running collection scripts there. The Linux and Python 3 requirements apply to the final monitored machine. Programs specified in a custom `ProxyCommand` run locally and must be available on the local machine.

Before updating, save edited files, handle terminal tasks, and exit through the tray menu. Pull the latest code and run `安装.cmd` again; existing machine configuration is retained and shortcuts are regenerated. Refreshing a page does not restart the backend.

The backend runs locally. **Do not share the `data` directory or SSH private keys.** Optional saved sudo passwords use Windows Credential Manager and can be removed. The assistant can write server files, execute authorized remote Shell commands, manage processes, and explicitly request sudo subject to server policy. It has no independent per-operation approval layer. Assistant conversations and server content actually read by its tools are sent to the configured model provider; do not ask it to read confidential files. Machine scope and credential protections remain enforced by the backend. See [data and credentials](SECURITY.md) in Chinese.

## What makes it AI-native

The assistant works with the workbench's actual machine, resource, process, file, and reservation tools. It can carry out multi-step tasks and expose tool results for review: find free devices, inspect processes, read a specified log, or create an availability alert using the conditions you confirmed. External agents can also access workbench capabilities through MCP.

Turn repeatable workflows into **Skills**. Create a skill in Settings, import Markdown or ZIP, or ask the assistant: “Turn the inspection workflow we just confirmed into a skill and install it.” Select skills with `@` in the composer, or let the assistant discover them as needed. Skills support persistent drafts, enable/disable controls, copying, export, and version rollback. Changes take effect on the next turn; scripts stored in skills do not run automatically.

The model interprets goals, selects tools, and explains results. The backend validates machine scope, arguments, and permissions. Execution records show target machines, parameters, results, and failures; uncertain resource states remain unknown. Resource searches and availability alerts do not lock devices or schedule training jobs.

Model APIs must support Responses and tool calls; local CLI engines require separate installation and authentication. The assistant can access all added hosts by default. Enable **Only allow operations on selected machines** in the composer context settings to restrict scope; sidebar selection alone does not restrict it. Cancellation does not undo completed changes.

## Development

See [CONTRIBUTING](CONTRIBUTING.md) and the [developer guide](docs/DEVELOPERS.en.md).

## License

This project is licensed under the [MIT License](LICENSE), which permits use, modification, distribution, and commercial and closed-source use, provided the copyright and license notices are retained when distributing the software. The software is provided as is, without warranty. Third-party dependencies remain subject to their own licenses.
