"""Read every model-space entity from CADCraft and write it as JSON.

By default it reads the drawing open in the running app, which must be started
with `open -a CADCraft --args --control 7979`. With --file it reads a drawing
headlessly instead.

    python3 scripts/cadcraft_read.py drawings/sample_apartment.entities.json
    python3 scripts/cadcraft_read.py out.json --file drawings/plan.dwg

The output holds the drawing summary (no entities) and the full entity list, as
returned by the MCP tools `inspect_drawing` and `query_entities`.
"""

import argparse
import json
import subprocess
import sys


class Mcp:
    def __init__(self, args):
        self.p = subprocess.Popen(
            ["cadcraft-cli", "mcp", *args],
            stdin=subprocess.PIPE, stdout=subprocess.PIPE, text=True,
        )
        self.n = 0
        self._rpc("initialize", {
            "protocolVersion": "2025-06-18", "capabilities": {},
            "clientInfo": {"name": "cadcraft_read", "version": "1"},
        })
        self._send({"jsonrpc": "2.0", "method": "notifications/initialized"})

    def _send(self, msg):
        self.p.stdin.write(json.dumps(msg) + "\n")
        self.p.stdin.flush()

    def _rpc(self, method, params):
        self.n += 1
        self._send({"jsonrpc": "2.0", "id": self.n, "method": method, "params": params})
        while True:
            line = self.p.stdout.readline()
            if not line:
                sys.exit("cadcraft-cli mcp exited (is CADCraft running with --control 7979?)")
            msg = json.loads(line)
            if msg.get("id") == self.n:
                break
        if "error" in msg:
            sys.exit(f"{method}: {msg['error']}")
        return msg["result"]

    def call(self, tool, **arguments):
        r = self._rpc("tools/call", {"name": tool, "arguments": arguments})
        text = r["content"][0]["text"]
        if r.get("isError"):
            sys.exit(f"{tool}: {text}")
        return json.loads(text)

    def close(self):
        self.p.stdin.close()
        self.p.terminate()


def main():
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("out", help="JSON file to write")
    ap.add_argument("--file", help="read this drawing headlessly instead of the running app")
    ap.add_argument("--port", default="127.0.0.1:7979")
    a = ap.parse_args()

    mcp = Mcp([] if a.file else ["--connect", a.port])
    try:
        if a.file:
            mcp.call("open", path=a.file)
        info = mcp.call("inspect_drawing", entities=False)
        entities, offset = [], 0
        while True:
            page = mcp.call("query_entities", offset=offset, limit=500)
            entities += page["entities"]
            offset += page["returned"]
            if page["returned"] == 0 or offset >= page["count"]:
                break
    finally:
        mcp.close()

    with open(a.out, "w") as f:
        json.dump({"drawing": info, "entities": entities}, f, indent=1)
    print(f"{info.get('title')}: {len(entities)} model-space entities -> {a.out}")


if __name__ == "__main__":
    main()
