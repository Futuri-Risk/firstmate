#!/usr/bin/env python3
"""External ACP protocol peer used against the real ACPx executable.

This is not a mock of FirstMate or ACPx. It replaces the unavailable paid
coding agent at the documented JSON-RPC transport boundary only.
"""
import json
from pathlib import Path
import sys
import uuid

log = Path(sys.argv[1])
store = log.with_suffix(".sessions.json")
sessions = json.loads(store.read_text()) if store.exists() else {}
waiting = None


def emit(value):
    print(json.dumps(value), flush=True)


def result(identifier, value):
    emit({"jsonrpc": "2.0", "id": identifier, "result": value})


for line in sys.stdin:
    message = json.loads(line)
    method, args, identifier = message.get("method"), message.get("params", {}), message.get("id")
    with log.open("a") as output:
        output.write(json.dumps({"method": method, "params": args}) + "\n")
    if method == "initialize":
        result(identifier, {"protocolVersion": 1, "agentCapabilities": {"loadSession": True},
                            "agentInfo": {"name": "fixture-peer", "version": "1"}})
    elif method == "session/new":
        session = str(uuid.uuid4())
        sessions[session] = args["cwd"]
        store.write_text(json.dumps(sessions))
        result(identifier, {"sessionId": session})
    elif method == "session/load":
        if args["sessionId"] in sessions:
            result(identifier, {})
        else:
            emit({"jsonrpc": "2.0", "id": identifier, "error": {"code": -32002, "message": "unknown session"}})
    elif method == "session/prompt":
        text = "".join(block.get("text", "") for block in args.get("prompt", []))
        if text.startswith("WAIT"):
            waiting = identifier
            continue
        if text.startswith("ERROR"):
            emit({"jsonrpc": "2.0", "id": identifier, "error": {"code": -32000, "message": "fixture failure"}})
            continue
        emit({"jsonrpc": "2.0", "method": "session/update", "params": {"sessionId": args["sessionId"],
              "update": {"sessionUpdate": "agent_message_chunk", "content": {"type": "text", "text": "RECEIVED:" + text}}}})
        result(identifier, {"stopReason": "end_turn"})
    elif method == "session/cancel":
        if waiting is not None:
            result(waiting, {"stopReason": "cancelled"})
            waiting = None
    elif method == "session/set_config_option":
        result(identifier, {"configOptions": []})
    elif identifier is not None:
        emit({"jsonrpc": "2.0", "id": identifier, "error": {"code": -32601, "message": "unsupported fixture method"}})
