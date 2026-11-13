"""Query Infra Workbench's local, stateless Streamable HTTP MCP endpoint."""
import argparse
import json
import os
import sys
from urllib.error import HTTPError
from urllib.parse import urlsplit
from urllib.request import HTTPRedirectHandler, ProxyHandler, Request, build_opener

QUERY_TOOLS = (
    "list_clusters",
    "get_cluster",
    "list_hosts",
    "find_hosts",
    "search_hosts",
    "get_host",
    "get_resources",
    "get_ssh_info",
)
PROTOCOL_VERSION = "2025-11-25"


class NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


def call(tool, arguments):
    """Return the tool envelope. Handle password results inside the caller."""
    url = os.environ.get("IWB_MCP_URL", "http://127.0.0.1:8765/mcp")
    endpoint = urlsplit(url)
    if endpoint.scheme != "http" or endpoint.hostname not in {"127.0.0.1", "localhost", "::1"}:
        raise ValueError("IWB_MCP_URL must use a local HTTP endpoint.")
    client = build_opener(ProxyHandler({}), NoRedirect())

    def send(method, params, request_id=None, protocol=None, session=None):
        message = {"jsonrpc": "2.0", "method": method, "params": params}
        if request_id is not None:
            message["id"] = request_id
        headers = {"Accept": "application/json, text/event-stream", "Content-Type": "application/json"}
        if protocol:
            headers["MCP-Protocol-Version"] = protocol
        if session:
            headers["MCP-Session-Id"] = session
        request = Request(url, data=json.dumps(message).encode("utf-8"), headers=headers)
        with client.open(request, timeout=35) as response:
            if request_id is None:
                return None, None
            reply = json.load(response)
            if reply.get("id") != request_id or "result" not in reply:
                raise ValueError(f"Invalid MCP response for {method}.")
            return reply["result"], response.headers.get("MCP-Session-Id")

    initialized, session = send("initialize", {
        "protocolVersion": PROTOCOL_VERSION,
        "capabilities": {},
        "clientInfo": {"name": "infra-workbench-ssh", "version": "1.0"},
    }, request_id=1)
    protocol = initialized["protocolVersion"]
    send("notifications/initialized", {}, protocol=protocol, session=session)
    result, _ = send(
        "tools/call", {"name": tool, "arguments": arguments},
        request_id=2, protocol=protocol, session=session,
    )
    return result["structuredContent"]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("tool", choices=QUERY_TOOLS)
    options = parser.parse_args()
    sys.stdout.reconfigure(encoding="utf-8")
    try:
        raw = sys.stdin.buffer.read().decode("utf-8-sig").strip() if not sys.stdin.isatty() else ""
        arguments = json.loads(raw) if raw else {}
        if not isinstance(arguments, dict):
            raise ValueError("Provide a JSON object on stdin.")
        result = call(options.tool, arguments)
    except HTTPError as error:
        parser.exit(1, f"Workbench returned HTTP {error.code}.\n")
    except (OSError, ValueError, KeyError) as error:
        parser.exit(1, f"Workbench query failed: {error}\n")
    print(json.dumps(result, ensure_ascii=False, separators=(",", ":")))
    return 0 if result.get("ok") else 1


if __name__ == "__main__":
    sys.exit(main())
