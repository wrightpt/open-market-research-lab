"""Fixed-route HTTPS client. No proxies, redirects, retries or service discovery."""

import http.client
import ipaddress
import queue
import re
import ssl
import threading
import time
from dataclasses import dataclass, field
from urllib.parse import urlsplit

from .bounds import MAX_REQUEST, MAX_RESPONSE, decode, encode

TOOLS = {
    "list_datasets": "List the caller's authorized dataset catalog.",
    "describe_dataset": "Describe sanitized dataset identity and provenance.",
    "get_coverage": "Read dataset coverage, gaps, and timing.",
    "get_schema": "Read field types, units, and missing-value meaning.",
    "query_timeseries": "Request a bounded authorized timeseries slice.",
    "get_research_examples": "Read reproducible research examples.",
    "get_usage_limits": "Read the caller's current usage and limits.",
}


class TransportError(Exception):
    """Messages are fixed and safe for the protocol; never wrap raw exceptions."""


@dataclass(frozen=True)
class Config:
    host: str
    port: int
    key: str = field(repr=False)
    ca_file: str | None = field(default=None, repr=False)

    @classmethod
    def from_env(cls, env):
        origin, key = env.get("OMR_API_URL", ""), env.get("OMR_API_KEY", "")
        if not origin or len(origin) > 2048 or any(ord(c) < 33 or ord(c) > 126 for c in origin):
            raise ValueError("OMR_API_URL must be an HTTPS origin")
        try:
            url = urlsplit(origin)
            host, port = url.hostname, 443 if url.port is None else url.port
        except ValueError:
            raise ValueError("OMR_API_URL must be an HTTPS origin") from None
        if (url.scheme != "https" or not host or "%" in host or url.username is not None or url.password is not None
                or url.path not in ("", "/") or "?" in origin or "#" in origin or not 1 <= port <= 65535):
            raise ValueError("OMR_API_URL must be an HTTPS origin")
        try:
            ipaddress.ip_address(host)
        except ValueError:
            if len(host) > 253 or any(not re.fullmatch(r"[A-Za-z0-9](?:[A-Za-z0-9-]{0,61}[A-Za-z0-9])?", p) for p in host.split(".")):
                raise ValueError("Invalid HTTPS hostname") from None
        if not 16 <= len(key) <= 2048 or any(ord(c) < 33 or ord(c) > 126 for c in key):
            raise ValueError("OMR_API_KEY must be 16-2048 printable non-space ASCII characters")
        return cls(host, port, key, env.get("OMR_CA_FILE") or None)


class ResearchClient:
    def __init__(self, config, timeout=10.0):
        if not 0 < timeout <= 10:
            raise ValueError("Timeout outside bound")
        self.config, self.timeout = config, timeout
        self.context = ssl.create_default_context(cafile=config.ca_file)
        self.context.minimum_version = ssl.TLSVersion.TLSv1_2
        self.slot = threading.BoundedSemaphore(1)

    def call(self, name, arguments, cancel_event=None):
        cancel_event = cancel_event or threading.Event()
        if cancel_event.is_set():
            raise TransportError("Research request cancelled")
        if not isinstance(name, str) or name not in TOOLS or not isinstance(arguments, dict):
            raise TransportError("Invalid research tool or arguments")
        try:
            payload = encode(arguments, MAX_REQUEST)
        except (ValueError, UnicodeError, RecursionError):
            raise TransportError("Research arguments exceed JSON bounds") from None
        if not self.slot.acquire(blocking=False):
            raise TransportError("HTTPS operation still active; wait or restart the adapter")
        result = queue.Queue(maxsize=1)
        deadline = time.monotonic() + self.timeout

        def work():
            try:
                result.put((True, self._exchange(name, payload, deadline, cancel_event)))
            except Exception:
                # Response bodies, headers, URLs and exception strings never escape.
                result.put((False, None))
            finally:
                self.slot.release()

        # Bounds DNS as well as TLS/headers/body from the caller's perspective.
        # At most one worker can remain stuck in a platform resolver; no new work
        # is admitted until it returns. A daemon never blocks EOF/process exit.
        threading.Thread(target=work, daemon=True).start()
        while True:
            if cancel_event.is_set():
                raise TransportError("Research request cancelled")
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                raise TransportError("HTTPS deadline exceeded; no automatic retry")
            try:
                ok, value = result.get(timeout=min(remaining, 0.05))
                break
            except queue.Empty:
                continue
        if not ok:
            raise TransportError("Research HTTPS request rejected or unavailable; no automatic retry")
        return value

    def _exchange(self, name, payload, deadline, cancel_event):
        connection = http.client.HTTPSConnection(self.config.host, self.config.port,
                                                  timeout=self.timeout, context=self.context)
        try:
            if cancel_event.is_set() or time.monotonic() >= deadline:
                raise TimeoutError()
            connection.connect()
            # A platform DNS resolver may return after the caller's deadline.
            # Never send the API key or request body after that late connect.
            remaining = deadline - time.monotonic()
            if cancel_event.is_set() or remaining <= 0:
                raise TimeoutError()
            connection.sock.settimeout(remaining)
            connection.request("POST", f"/v1/research/tools/{name}", body=payload,
                               headers={"X-API-Key": self.config.key, "Content-Type": "application/json",
                                        "X-QMA-Client-Transport": "mcp-public-adapter",
                                        "Accept": "application/json", "Accept-Encoding": "identity",
                                        "Connection": "close"})
            response = connection.getresponse()
            if response.status != 200:  # Includes every redirect; never follow Location.
                raise ValueError("HTTP status rejected")
            if response.getheader("Content-Type", "").split(";")[0].strip().lower() != "application/json":
                raise ValueError("JSON required")
            if response.getheader("Content-Encoding", "identity").lower() != "identity":
                raise ValueError("No compressed responses")
            size = response.getheader("Content-Length")
            if size is not None and (not size.isdecimal() or not 0 <= int(size) <= MAX_RESPONSE):
                raise ValueError("Response byte limit")
            chunks, total = [], 0
            while True:
                remaining = deadline - time.monotonic()
                if cancel_event.is_set() or remaining <= 0:
                    raise TimeoutError()
                # The outer deadline also covers slow fragmented HTTP headers.
                chunk = response.read1(min(8192, MAX_RESPONSE + 1 - total))
                if not chunk:
                    break
                total += len(chunk)
                if total > MAX_RESPONSE:
                    raise ValueError("Response byte limit")
                chunks.append(chunk)
            raw = b"".join(chunks)
            if size is not None and len(raw) != int(size):
                raise ValueError("Truncated response")
            value = decode(raw, MAX_RESPONSE)
            if not isinstance(value, dict):
                raise ValueError("Backend result must be an object")
            # Even a misconfigured upstream must not reflect this credential to an LLM.
            def reflected(item):
                if isinstance(item, str):
                    return self.config.key in item
                if isinstance(item, dict):
                    return any(reflected(k) or reflected(v) for k, v in item.items())
                if isinstance(item, list):
                    return any(reflected(v) for v in item)
                return False

            if reflected(value) or self.config.key in raw.decode("utf-8"):
                raise ValueError("Credential reflection")
            return value
        finally:
            connection.close()
