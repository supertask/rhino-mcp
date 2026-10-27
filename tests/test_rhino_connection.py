# -*- coding: utf-8 -*-
"""Tests for the MCP-side Rhino connection (src/rhino_mcp/rhino_tools.py).

A fake Rhino bridge runs on an ephemeral localhost port, so neither Rhino nor
port 9876 is touched. Run with:  python -m unittest discover -s tests -v
"""
import json
import os
import socket
import struct
import sys
import threading
import time
import types
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "src"))


def _install_stub_modules():
    """rhino_tools only needs FastMCP/Image/PIL names at import time."""
    if "mcp.server.fastmcp" not in sys.modules:
        fastmcp = types.ModuleType("mcp.server.fastmcp")

        class FastMCP(object):
            def __init__(self, *args, **kwargs):
                self.tools = []

            def tool(self):
                def register(fn):
                    self.tools.append(fn)
                    return fn
                return register

        fastmcp.FastMCP = FastMCP
        fastmcp.Context = object
        fastmcp.Image = object
        sys.modules.setdefault("mcp", types.ModuleType("mcp"))
        sys.modules.setdefault("mcp.server", types.ModuleType("mcp.server"))
        sys.modules["mcp.server.fastmcp"] = fastmcp
    if "PIL" not in sys.modules:
        pil = types.ModuleType("PIL")
        pil.Image = types.ModuleType("PIL.Image")
        sys.modules["PIL"] = pil
        sys.modules["PIL.Image"] = pil.Image


try:
    import mcp.server.fastmcp  # noqa: F401  (use the real package when installed)
except Exception:
    for name in [n for n in sys.modules if n == "mcp" or n.startswith("mcp.")]:
        del sys.modules[name]
    _install_stub_modules()

from rhino_mcp import rhino_tools  # noqa: E402
from rhino_mcp.rhino_tools import (  # noqa: E402
    RhinoCommandError,
    RhinoConnection,
    RhinoConnectionError,
    RhinoResultUnknownError,
)

JP_LAYER = u"レイヤー_日本語"


class FakeRhino(object):
    """A minimal stand-in for rhino_mcp_bridge.py.

    `behaviour` maps a command type to one of:
      "reply"         - answer normally (UTF-8 JSON, split mid-character)
      "error"         - answer with status=error
      "close"         - read the command, then close without answering
      "reset"         - read the command, then reset the connection (RST)
      "silent"        - read the command and never answer
    `behaviour_once` applies to the first occurrence only.
    """

    def __init__(self):
        self.listener = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self.listener.bind(("127.0.0.1", 0))
        self.listener.listen(5)
        self.port = self.listener.getsockname()[1]
        self.received = []          # (connection number, command type)
        self.behaviour = {}
        self.behaviour_once = {}
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
                else:
                    response = {"status": "success", "type": cmd_type, "layer": JP_LAYER}
                payload = json.dumps(response, ensure_ascii=False).encode("utf-8")
                # Split inside a multi-byte character to exercise reassembly
                cut = next(i for i, b in enumerate(payload) if b >= 0x80) + 1
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

    def close(self):
        self.running = False
        self.drop_all_connections()
        self.listener.close()


class RhinoConnectionTests(unittest.TestCase):
    def setUp(self):
        self.rhino = FakeRhino()
        self.conn = RhinoConnection(host="127.0.0.1", port=self.rhino.port)

    def tearDown(self):
        self.conn.disconnect()
        self.rhino.close()

    def test_normal_command_and_japanese_split_utf8(self):
        result = self.conn.send_command("get_layers")
        self.assertEqual(result["layer"], JP_LAYER)
        # The connection is reused for the next command
        self.conn.send_command("get_layers")
        self.assertEqual([n for n, _ in self.rhino.commands("get_layers")], [1, 1])

    def test_rhino_restart_does_not_fail_first_command(self):
        self.conn.send_command("get_layers")
        self.rhino.drop_all_connections()   # Rhino restarted
        time.sleep(0.1)
        result = self.conn.send_command("execute_code", {"code": "pass"})
        self.assertEqual(result["status"], "success")
        # Delivered exactly once, on a new connection
        self.assertEqual(self.rhino.commands("execute_code"), [(2, "execute_code")])

    def test_modifying_command_is_not_resent_when_connection_closes(self):
        self.rhino.behaviour_once["execute_code"] = "close"
        with self.assertRaises(RhinoResultUnknownError) as ctx:
            self.conn.send_command("execute_code", {"code": "pass"})
        self.assertIn(u"二重実行", str(ctx.exception))
        time.sleep(0.1)
        self.assertEqual(len(self.rhino.commands("execute_code")), 1)
        # The next operation works on a fresh connection
        self.assertEqual(self.conn.send_command("get_layers")["status"], "success")

    def test_modifying_command_is_not_resent_on_reset(self):
        self.rhino.behaviour_once["capture_viewport"] = "reset"
        with self.assertRaises(RhinoResultUnknownError):
            self.conn.send_command("capture_viewport", {})
        time.sleep(0.1)
        self.assertEqual(len(self.rhino.commands("capture_viewport")), 1)

    def test_read_only_command_is_retried_once(self):
        self.rhino.behaviour_once["get_scene_info"] = "reset"
        result = self.conn.send_command("get_scene_info")
        self.assertEqual(result["status"], "success")
        self.assertEqual([n for n, _ in self.rhino.commands("get_scene_info")], [1, 2])

    def test_read_only_command_gives_up_after_one_retry(self):
        self.rhino.behaviour["get_layers"] = "close"
        with self.assertRaises(RhinoResultUnknownError):
            self.conn.send_command("get_layers")
        time.sleep(0.1)
        self.assertEqual(len(self.rhino.commands("get_layers")), 2)

    def test_timeout_is_result_unknown_and_late_reply_is_not_mixed_in(self):
        self.conn.timeout = 0.5
        self.rhino.behaviour_once["execute_code"] = "silent"
        with self.assertRaises(RhinoResultUnknownError):
            self.conn.send_command("execute_code", {"code": "pass"})
        self.assertEqual(len(self.rhino.commands("execute_code")), 1)
        result = self.conn.send_command("get_layers")
        self.assertEqual(result["type"], "get_layers")
        self.assertEqual(self.rhino.commands("get_layers"), [(2, "get_layers")])

    def test_error_from_rhino_keeps_connection(self):
        self.rhino.behaviour_once["execute_code"] = "error"
        with self.assertRaises(RhinoCommandError) as ctx:
            self.conn.send_command("execute_code", {"code": "x"})
        self.assertIn(u"Rhino側のエラー", str(ctx.exception))
        self.conn.send_command("get_layers")
        self.assertEqual(self.rhino.commands("get_layers"), [(1, "get_layers")])

    def test_rhino_not_running(self):
        port = self.rhino.port
        self.rhino.close()
        conn = RhinoConnection(host="127.0.0.1", port=port)
        with self.assertRaises(RhinoConnectionError) as ctx:
            conn.send_command("execute_code", {"code": "pass"})
        self.assertIn(u"Rhinoに接続できません", str(ctx.exception))


class RhinoToolsOutputTests(unittest.TestCase):
    def setUp(self):
        self.rhino = FakeRhino()
        self._saved = rhino_tools._rhino_connection
        rhino_tools._rhino_connection = RhinoConnection(host="127.0.0.1", port=self.rhino.port)
        self.tools = rhino_tools.RhinoTools(sys.modules["mcp.server.fastmcp"].FastMCP("test"))

    def tearDown(self):
        rhino_tools._rhino_connection.disconnect()
        rhino_tools._rhino_connection = self._saved
        self.rhino.close()

    def test_japanese_is_readable_in_tool_output(self):
        text = self.tools.get_layers(None)
        self.assertIn(JP_LAYER, text)
        self.assertNotIn("\\u30ec", text)

    def test_unknown_result_reaches_the_model_as_text(self):
        self.rhino.behaviour_once["execute_code"] = "close"
        text = self.tools.execute_rhino_code(None, "result = 1")
        self.assertIn(u"自動では再送していません", text)
        time.sleep(0.1)
        self.assertEqual(len(self.rhino.commands("execute_code")), 1)


if __name__ == "__main__":
    unittest.main()
