# -*- coding: utf-8 -*-
"""Fake Rhino / Grasshopper bridges listening on ephemeral localhost ports.

Neither Rhino nor the real ports (9876 / 9999) are used.
"""
import json
import socket
import struct
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

JP_LAYER = u"レイヤー_日本語"


def free_port():
    s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    s.bind(("127.0.0.1", 0))
    port = s.getsockname()[1]
    s.close()
    return port


class FakeRhino(object):
    """A minimal stand-in for rhino_mcp_bridge.py (raw JSON over TCP).

    `behaviour` maps a command type to one of:
      "reply"  - answer normally (UTF-8 JSON, split mid-character)
      "error"  - answer with status=error
      "close"  - read the command, then close without answering
      "reset"  - read the command, then reset the connection (RST)
      "silent" - read the command and never answer
    `behaviour_once` applies to the first occurrence only.
    `responses` maps a command type to the dict to answer with.
    """

    def __init__(self):
        self.listener = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self.listener.bind(("127.0.0.1", 0))
        self.listener.listen(5)
        self.port = self.listener.getsockname()[1]
        self.received = []          # (connection number, command type)
        self.payloads = []          # full commands, in order
        self.behaviour = {}
        self.behaviour_once = {}
        self.responses = {}
        self.connections = []
        self.lock = threading.Lock()
        self.running = True
        threading.Thread(target=self._accept_loop, daemon=True).start()

    def _accept_loop(self):
        while self.running:
            try:
                conn, _ = self.listener.accept()
            except OSError:
                return
            with self.lock:
                self.connections.append(conn)
                number = len(self.connections)
            threading.Thread(target=self._serve, args=(conn, number), daemon=True).start()

    def _serve(self, conn, number):
        buffer = b""
        try:
            while True:
                data = conn.recv(65536)
                if not data:
                    return
                buffer += data
                try:
                    command = json.loads(buffer.decode("utf-8"))
                except ValueError:
                    continue
                buffer = b""
                cmd_type = command["type"]
                with self.lock:
                    self.received.append((number, cmd_type))
                    self.payloads.append(command)
                    action = self.behaviour_once.pop(cmd_type, None) or self.behaviour.get(cmd_type, "reply")
                if action == "close":
                    conn.close()
                    return
                if action == "reset":
                    conn.setsockopt(socket.SOL_SOCKET, socket.SO_LINGER, struct.pack("ii", 1, 0))
                    conn.close()
                    return
                if action == "silent":
                    continue
                if action == "error":
                    response = {"status": "error", "message": u"Rhino側のエラー"}
                elif cmd_type in self.responses:
                    response = self.responses[cmd_type]
                else:
                    response = {"status": "success", "type": cmd_type, "layer": JP_LAYER}
                payload = json.dumps(response, ensure_ascii=False).encode("utf-8")
                # Split inside a multi-byte character to exercise reassembly
                non_ascii = [i for i, b in enumerate(payload) if b >= 0x80]
                cut = non_ascii[0] + 1 if non_ascii else len(payload) // 2
                conn.sendall(payload[:cut])
                time.sleep(0.02)
                conn.sendall(payload[cut:])
        except OSError:
            return

    def drop_all_connections(self):
        """Simulate Rhino being closed and started again (old sockets die, port stays open)."""
        with self.lock:
            for conn in self.connections:
                try:
                    conn.close()
                except OSError:
                    pass

    def commands(self, cmd_type):
        with self.lock:
            return [c for c in self.received if c[1] == cmd_type]

    def last_payload(self, cmd_type):
        with self.lock:
            return [p for p in self.payloads if p["type"] == cmd_type][-1]

    def close(self):
        self.running = False
        self.drop_all_connections()
        self.listener.close()


class FakeGrasshopper(object):
    """A stand-in for grasshopper_mcp_bridge.py (JSON over HTTP POST).

    `responses` maps a command type to a dict (sent as JSON), an int HTTP
    status code, or a float: seconds to wait before a normal answer.
    Unlisted commands get {"status": "success", ...}.
    """

    def __init__(self):
        self.requests = []
        self.responses = {}
        fake = self

        class Handler(BaseHTTPRequestHandler):
            def do_POST(self):
                length = int(self.headers.get("Content-Length", 0))
                body = json.loads(self.rfile.read(length).decode("utf-8"))
                fake.requests.append(body)
                default = {"status": "success", "result": {"type": body.get("type")}}
                response = fake.responses.get(body.get("type"), default)
                if isinstance(response, float):
                    time.sleep(response)
                    response = default
                if isinstance(response, int):
                    self.send_response(response)
                    self.send_header("Content-Length", "0")
                    self.end_headers()
                    return
                data = json.dumps(response).encode("utf-8")
                self.send_response(200)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(data)))
                self.end_headers()
                self.wfile.write(data)

            def log_message(self, *args):
                pass

        self.server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        self.port = self.server.server_address[1]
        threading.Thread(target=self.server.serve_forever, daemon=True).start()

    def types(self):
        return [r.get("type") for r in self.requests]

    def last(self, cmd_type):
        return [r for r in self.requests if r.get("type") == cmd_type][-1]

    def close(self):
        self.server.shutdown()
        self.server.server_close()
