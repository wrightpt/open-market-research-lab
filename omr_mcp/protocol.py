"""Dual-era MCP subset: discovery, ping, seven tools, cancellation, no execution."""

import threading

from . import __version__
from .bounds import MAX_REQUEST, MAX_RESPONSE, encode
from .client import TOOLS, TransportError

MODERN = "2026-07-28"
LEGACY = "2025-11-25"
PREFIX = "io.modelcontextprotocol/"
INFO = {"name": "open-market-research-lab", "version": __version__}


def valid_id(value):
    return type(value) is int and abs(value) <= 2**53 - 1 or isinstance(value, str) and len(value) <= 256


def error(identifier, code, message, data=None):
    result = {"jsonrpc": "2.0", "error": {"code": code, "message": message}}
    if identifier is not None:
        result["id"] = identifier
    if data is not None:
        result["error"]["data"] = data
    return result


def complete(identifier, result, modern):
    if modern:
        result = {**result, "resultType": "complete", "_meta": {PREFIX + "serverInfo": INFO}}
    return {"jsonrpc": "2.0", "id": identifier, "result": result}


class Protocol:
    def __init__(self, client):
        self.client = client
        self.legacy_initialized = False
        self.legacy_ready = False

    def prepare(self, request):
        """Return a response or deferred callable; notifications return None."""
        if not isinstance(request, dict):
            return error(None, -32600, "Invalid request; batches are not supported")
        identifier = request.get("id")
        if (request.get("jsonrpc") != "2.0" or not isinstance(request.get("method"), str)
                or ("id" in request and not valid_id(identifier))
                or set(request) - {"jsonrpc", "id", "method", "params"}):
            return error(identifier if valid_id(identifier) else None, -32600, "Invalid request")
        method, params = request["method"], request.get("params", {})
        if "id" not in request:
            if method == "notifications/initialized" and self.legacy_initialized:
                self.legacy_ready = True
            return None  # Notifications can never trigger HTTPS or receive replies.
        if not isinstance(params, dict):
            return error(identifier, -32602, "Parameters must be an object")
        meta = params.get("_meta", {})
        if not isinstance(meta, dict):
            return error(identifier, -32602, "Invalid metadata")
        has_modern = any(PREFIX + key in meta for key in ("protocolVersion", "clientCapabilities", "clientInfo"))
        if method == "initialize" and not has_modern:
            if (params.get("protocolVersion") != LEGACY or not isinstance(params.get("capabilities"), dict)
                    or not isinstance(params.get("clientInfo"), dict)
                    or not all(isinstance(params["clientInfo"].get(k), str) for k in ("name", "version"))):
                return error(identifier, -32602, "Legacy initialize supports 2025-11-25 only")
            if self.legacy_initialized:
                return error(identifier, -32600, "Legacy session already initialized")
            self.legacy_initialized = True
            return complete(identifier, {"protocolVersion": LEGACY, "capabilities": {"tools": {}}, "serverInfo": INFO}, False)
        modern = has_modern or not self.legacy_ready or method == "server/discover"
        if modern:
            version = meta.get(PREFIX + "protocolVersion")
            if not isinstance(version, str) or not isinstance(meta.get(PREFIX + "clientCapabilities"), dict):
                return error(identifier, -32602, "Per-request protocolVersion and clientCapabilities required")
            if version != MODERN:
                return error(identifier, -32022, "Unsupported protocol version",
                             {"supported": [MODERN, LEGACY], "requested": version})
            client_info = meta.get(PREFIX + "clientInfo")
            if client_info is not None and (not isinstance(client_info, dict) or not all(isinstance(client_info.get(k), str) for k in ("name", "version"))):
                return error(identifier, -32602, "Invalid clientInfo")
        if method == "server/discover":
            return complete(identifier, {"supportedVersions": [MODERN, LEGACY], "capabilities": {"tools": {}},
                                         "ttlMs": 0, "cacheScope": "private"}, modern)
        if method == "ping":
            return complete(identifier, {}, modern)
        if method == "tools/list":
            if params.get("cursor") is not None:
                return error(identifier, -32602, "Pagination is not supported")
            listing = {"tools": [{"name": name, "description": description + " Backend owns argument validation and access; JSON object passthrough.",
                                  "inputSchema": {"type": "object", "additionalProperties": True},
                                  "annotations": {"readOnlyHint": True, "openWorldHint": True}}
                                 for name, description in TOOLS.items()]}
            if modern:
                listing.update(ttlMs=0, cacheScope="private")
            return complete(identifier, listing, modern)
        if method != "tools/call":
            return error(identifier, -32601, "Method not supported")
        name, arguments = params.get("name"), params.get("arguments", {})
        if not isinstance(name, str) or name not in TOOLS or not isinstance(arguments, dict):
            return error(identifier, -32602, "Unknown tool or non-object arguments")
        if set(params) - {"name", "arguments", "_meta"}:
            return error(identifier, -32602, "Unsupported tool parameters")
        try:
            encode(arguments, MAX_REQUEST)
        except (ValueError, UnicodeError, RecursionError):
            return error(identifier, -32602, "Research arguments exceed JSON bounds")

        cancel_event = threading.Event()

        def invoke():
            try:
                data = self.client.call(name, arguments, cancel_event=cancel_event)
                result = {"content": [{"type": "text", "text": encode(data, MAX_RESPONSE).decode("utf-8")}],
                          "structuredContent": data, "isError": False}
            except TransportError as exc:
                result = {"content": [{"type": "text", "text": str(exc)}], "isError": True}
            except Exception:
                result = {"content": [{"type": "text", "text": "Research request unavailable"}], "isError": True}
            return complete(identifier, result, modern)

        invoke.cancel = cancel_event.set
        return invoke
