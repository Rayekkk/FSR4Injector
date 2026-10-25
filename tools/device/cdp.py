#!/usr/bin/env python3
"""Minimal Chrome DevTools Protocol client for the Steam client's CEF debugger (127.0.0.1:8080), stdlib only.

  cdp.py eval <javascript>   print the JSON result (promises are awaited)
  cdp.py shot <out.png> [x y w h]  screenshot of the target page, optionally clipped (CSS pixels)
Target: the page titled $CDP_TARGET (default SharedJSContext), e.g. QuickAccess_uid2 for the Quick Access Menu.
"""

import base64
import json
import os
import socket
import struct
import sys
import urllib.request

PORT = 8080


def _target():
    title = os.environ.get("CDP_TARGET", "SharedJSContext")
    with urllib.request.urlopen(f"http://127.0.0.1:{PORT}/json") as r:
        for t in json.load(r):
            if t.get("title") == title:
                return t["webSocketDebuggerUrl"]
    sys.exit(f"no CEF target titled {title!r}")


class _Socket:
    def __init__(self, url):
        rest = url.split("://", 1)[1]
        hostport, path = rest.split("/", 1)
        host, port = hostport.split(":")
        self.s = socket.create_connection((host, int(port)), timeout=30)
        key = base64.b64encode(os.urandom(16)).decode()
        self.s.sendall((f"GET /{path} HTTP/1.1\r\nHost: {hostport}\r\nUpgrade: websocket\r\nConnection: Upgrade\r\n"
                        f"Sec-WebSocket-Key: {key}\r\nSec-WebSocket-Version: 13\r\n\r\n").encode())
        head = b""
        while b"\r\n\r\n" not in head:
            head += self.s.recv(1)
        if b" 101 " not in head.split(b"\r\n", 1)[0]:
            sys.exit("websocket handshake failed")

    def _read(self, n):
        buf = b""
        while len(buf) < n:
            chunk = self.s.recv(n - len(buf))
            if not chunk:
                raise ConnectionError("CEF closed the connection")
            buf += chunk
        return buf

    def send(self, text):
        data, mask = text.encode(), os.urandom(4)
        n = len(data)
        head = bytes([0x81]) + (bytes([0x80 | n]) if n < 126 else
                                struct.pack(">BH", 0x80 | 126, n) if n < 65536 else struct.pack(">BQ", 0x80 | 127, n))
        self.s.sendall(head + mask + bytes(b ^ mask[i % 4] for i, b in enumerate(data)))

    def recv(self):
        message = b""
        while True:
            b0, b1 = self._read(2)
            n = b1 & 0x7F
            if n == 126:
                n = struct.unpack(">H", self._read(2))[0]
            elif n == 127:
                n = struct.unpack(">Q", self._read(8))[0]
            message += self._read(n)
            if b0 & 0x80:  # FIN
                return message.decode()


def call(method, params):
    ws = _Socket(_target())
    ws.send(json.dumps({"id": 1, "method": method, "params": params}))
    while True:
        reply = json.loads(ws.recv())
        if reply.get("id") == 1:
            return reply


def main():
    if len(sys.argv) == 3 and sys.argv[1] == "eval":
        reply = call("Runtime.evaluate", {"expression": sys.argv[2], "awaitPromise": True, "returnByValue": True})
        result = reply.get("result", {})
        if "exceptionDetails" in result:
            sys.exit(json.dumps(result["exceptionDetails"].get("exception", {}).get("description", "exception")))
        print(json.dumps(result.get("result", {}).get("value")))
    elif len(sys.argv) in (3, 7) and sys.argv[1] == "shot":
        params = {"format": "png"}
        if len(sys.argv) == 7:  # clip x y width height, in CSS pixels
            x, y, w, h = map(float, sys.argv[3:])
            params["clip"] = {"x": x, "y": y, "width": w, "height": h, "scale": 1}
        reply = call("Page.captureScreenshot", params)
        with open(sys.argv[2], "wb") as f:
            f.write(base64.b64decode(reply["result"]["data"]))
    else:
        sys.exit(__doc__)


if __name__ == "__main__":
    main()
