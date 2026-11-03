# Remote service forwarding

Open **Services** on a machine card. Save a named TensorBoard (6006), Jupyter (8888), or custom HTTP rule. Local port 0 selects a free port. Rules persist; tunnels never restart automatically. Start and stop each rule explicitly. Delete stops its listener before removing the rule. All listeners bind only `127.0.0.1` and forward only to remote `127.0.0.1`.

Active means an SSH listener has been established, not that the remote application is healthy. Start the application on the remote machine separately. Enter Jupyter tokens in Jupyter itself; the workbench does not collect them. Close the panel to keep tunnels running; removing the host or shutting down the backend stops them.

Existing verified AsyncSSH password sessions are reused. Otherwise native OpenSSH runs with strict host-key checking, batch authentication, no remote command, and forwarding failure detection. The main connection uses an isolated resolved configuration to exclude inherited forwards. Jump aliases use a separate `ssh -W` child which resolves the original jump configuration and clears forwarding. No passwords are exported and no remote keys are installed.

Shared MCP tools `list_services`, `create_service`, `start_service`, `stop_service`, and `delete_service` reuse the same routes. All require `host_id`; opaque rule IDs are checked against that host. Creation/start descriptions require explicit user requests. Tunnel lifecycle is bound to the backend, not an individual chat.

Validation includes local synthetic SSH servers with real AsyncSSH and installed OpenSSH roundtrips. Production SSH endpoints are not modified during tests.
