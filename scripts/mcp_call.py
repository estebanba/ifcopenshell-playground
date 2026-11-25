"""Call Blender MCP tools directly over stdio, without Claude Code's MCP integration.

Useful for smoke tests or when the session hasn't loaded the `blender` server.
Requires Blender running with the add-on started (localhost:9876).

Usage:
  python3 scripts/mcp_call.py '[["get_addon_status", {}], ["get_scene_info", {}]]'
  python3 scripts/mcp_call.py '[["execute_blender_code", {"code": "import bpy; print(bpy.app.version_string)"}]]'
"""
import json
import os
import subprocess
import sys

ENV = {**os.environ, "DISABLE_TELEMETRY": "true", "BLENDERMCP_NO_UPDATE_CHECK": "1",
       "BLENDER_HOST": "localhost", "BLENDER_PORT": "9876"}
proc = subprocess.Popen(["uvx", "mcp-for-blender==2.2.7"], stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                        stderr=subprocess.DEVNULL, env=ENV, text=True)


def send(msg):
    proc.stdin.write(json.dumps(msg) + "\n")
    proc.stdin.flush()


def recv(msg_id):
    while True:
        msg = json.loads(proc.stdout.readline())
        if msg.get("id") == msg_id:
            return msg


send({"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {
    "protocolVersion": "2025-06-18", "capabilities": {}, "clientInfo": {"name": "mcp_call", "version": "0"}}})
recv(1)
send({"jsonrpc": "2.0", "method": "notifications/initialized"})
for n, (name, args) in enumerate(json.loads(sys.argv[1]), start=2):
    send({"jsonrpc": "2.0", "id": n, "method": "tools/call", "params": {"name": name, "arguments": args}})
    reply = recv(n)
    print(f"### {name}")
    for item in reply.get("result", {}).get("content", []) or [reply.get("error")]:
        print(item.get("text", item) if isinstance(item, dict) else item)
proc.terminate()
