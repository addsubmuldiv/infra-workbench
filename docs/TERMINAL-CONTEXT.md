# Terminal context attachments

The terminal toolbar explicitly captures either the selection or the currently visible xterm viewport. It does not subscribe the assistant to output or execute input. Captures contain machine ID/label, local terminal tab ID, persistent session ID when available, last known cwd, capture timestamp and source. Unknown cwd is shown explicitly.

Each capture is limited to 150 lines and 12,000 Unicode code points, with truncation recorded; at most three captures can be pending or sent per message. Controls are stripped. Attachments remain in window memory until submitted, and opening the assistant preserves the existing message draft. The user can inspect/remove captures before sending a separate instruction. Standalone terminal windows open an assistant in the same window, retaining their capture without cross-window persistence.

The server independently checks shape, bounds, known machine IDs and restricted machine scope. It scrubs credentials before persistence/model use and labels terminal output as untrusted data, never as authorization. Both Deep Agents and Codex receive the attachment in the explicit user turn. The visible receipt remains plain React text; output is never rendered as HTML. The 4,000-character user instruction limit remains separate. This feature does not expand MCP machine permissions.
