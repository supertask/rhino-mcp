# -*- coding: utf-8 -*-
"""Tests for the request handling in rhino_scripts/grasshopper_mcp_bridge.py.

The bridge's real server_loop() runs in CPython on an ephemeral port (not
9999), with Rhino/Grasshopper modules mocked. The parts that talk to the
Grasshopper API are replaced by fakes; only HTTP handling and the generic
parts of process_command() are tested.
Tests marked "既知の問題" document current behaviour that should change.
Run with:  python -m unittest discover -s tests -v

Limitation: runs on CPython, not IronPython 2.7.
"""
import json
import socket
import threading
import time
import unittest

from helpers import stubs
from helpers.fake_servers import free_port


def http_post(port, body_bytes, chunks=1, delay=0.05, path="/"):
    """Send a POST with a raw socket, optionally splitting the body."""
    s = socket.create_connection(("127.0.0.1", port), timeout=10)
    head = "POST {0} HTTP/1.1\r\nHost: localhost\r\nContent-Type: application/json\r\nContent-Length: {1}\r\n\r\n".format(
        path, len(body_bytes)).encode("ascii")
    s.sendall(head)
    step = max(1, len(body_bytes) // chunks)
    for i in range(0, len(body_bytes), step):
        time.sleep(delay)
        s.sendall(body_bytes[i:i + step])
    return read_http_response(s)


def read_http_response(s):
    data = b""
    while b"\r\n\r\n" not in data:
        chunk = s.recv(4096)
        if not chunk:
            break
        data += chunk
    head, body = data.split(b"\r\n\r\n", 1)
    length = 0
    for line in head.decode("ascii").split("\r\n"):
        if line.lower().startswith("content-length:"):
            length = int(line.split(":")[1])
    while len(body) < length:
        chunk = s.recv(65536)
        if not chunk:
            break
        body += chunk
    s.close()
    return head.decode("ascii"), body, length


class BridgeServerTestCase(unittest.TestCase):
    def setUp(self):
        self.builtins_patch = stubs.py2_builtins()
        self.builtins_patch.__enter__()
        self.bridge = stubs.load_bridge("grasshopper_mcp_bridge.py", grasshopper=True)
        self.port = free_port()
        self.bridge.PORT = self.port
        self.received = []

        def fake_process_command(cmd):
            self.received.append(cmd)
            if cmd.get("type") == "raise":
                raise RuntimeError("boom")
            if cmd.get("type") == "big":
                return {"status": "success", "result": "x" * 200000}
            return {"status": "success", "result": u"受信: " + cmd.get("text", "")}

        self.bridge.process_command = fake_process_command
        self.sticky = self.bridge.sc.sticky
        self.sticky["gh_mcp_run_server"] = True
        self.thread = threading.Thread(target=self.bridge.server_loop, daemon=True)
        self.thread.start()
        for _ in range(50):
            try:
                socket.create_connection(("127.0.0.1", self.port), timeout=0.2).close()
                break
            except OSError:
                time.sleep(0.05)
        # The probe above is itself an empty connection; start from a clean log
        time.sleep(0.2)
        self.bridge.Rhino.RhinoApp.WriteLine.reset_mock()
        self.received[:] = []

    def tearDown(self):
        self.sticky["gh_mcp_run_server"] = False
        self.thread.join(3)
        self.builtins_patch.__exit__(None, None, None)

    def lines(self):
        return stubs.rhino_lines(self.bridge)


class HttpHandlingTests(BridgeServerTestCase):
    def test_post_with_japanese_body_and_response(self):
        body = json.dumps({"type": "echo", "text": u"日本語"}, ensure_ascii=False).encode("utf-8")
        head, data, length = http_post(self.port, body)
        self.assertIn("200 OK", head)
        self.assertEqual(len(data), length)           # Content-Length matches the bytes sent
        self.assertEqual(json.loads(data.decode("utf-8"))["result"], u"受信: 日本語")
        self.assertEqual(self.received[0]["text"], u"日本語")

    def test_body_split_across_packets(self):
        body = json.dumps({"type": "echo", "text": u"分割" * 3000}, ensure_ascii=False).encode("utf-8")
        head, data, _ = http_post(self.port, body, chunks=5)
        self.assertEqual(json.loads(data.decode("utf-8"))["result"], u"受信: " + u"分割" * 3000)

    def test_large_response(self):
        _, data, length = http_post(self.port, b'{"type": "big"}')
        self.assertEqual(length, len(data))
        self.assertEqual(len(json.loads(data.decode("utf-8"))["result"]), 200000)

    def test_options_preflight(self):
        s = socket.create_connection(("127.0.0.1", self.port), timeout=10)
        s.sendall(b"OPTIONS / HTTP/1.1\r\nHost: localhost\r\n\r\n")
        head, _, _ = read_http_response(s)
        self.assertIn("200 OK", head)
        self.assertIn("Access-Control-Allow-Origin: *", head)
        self.assertEqual(self.received, [])

    def test_invalid_json_gets_error_response_and_server_keeps_running(self):
        _, data, _ = http_post(self.port, b"{not json")
        self.assertEqual(json.loads(data.decode("utf-8"))["status"], "error")
        _, data, _ = http_post(self.port, b'{"type": "echo", "text": "next"}')
        self.assertEqual(json.loads(data.decode("utf-8"))["result"], u"受信: next")

    def test_exception_in_command_is_reported(self):
        _, data, _ = http_post(self.port, b'{"type": "raise"}')
        response = json.loads(data.decode("utf-8"))
        self.assertEqual(response["status"], "error")
        self.assertIn("boom", response["result"])
        self.assertTrue(any("Error in process_command: boom" in l for l in self.lines()))

    def test_stop_flag_ends_loop_and_frees_port(self):
        self.sticky["gh_mcp_run_server"] = False
        self.thread.join(3)
        self.assertFalse(self.thread.is_alive())
        # A normal stop (flag turned off) intentionally prints no "stopped" message
        with self.assertRaises(OSError):
            socket.create_connection(("127.0.0.1", self.port), timeout=0.5)

    @unittest.expectedFailure
    def test_known_issue_empty_connection_prints_error(self):
        """既知の問題: 何も送らずに閉じた接続（接続確認など）で、
        Rhino のコマンドラインに「[MCP] Error ...」が表示される。"""
        http_post(self.port, b'{"type": "echo"}')
        self.bridge.Rhino.RhinoApp.WriteLine.reset_mock()
        socket.create_connection(("127.0.0.1", self.port), timeout=1).close()
        time.sleep(0.5)
        self.assertEqual(self.lines(), [])


class ProcessCommandTests(unittest.TestCase):
    """The generic parts of the real process_command()."""

    def setUp(self):
        self.builtins_patch = stubs.py2_builtins()
        self.builtins_patch.__enter__()
        self.bridge = stubs.load_bridge("grasshopper_mcp_bridge.py", grasshopper=True)
        self.bridge.Action = lambda fn: fn
        self.ui_calls = []

    def tearDown(self):
        self.builtins_patch.__exit__(None, None, None)

    def _ui_thread(self, delay=0.0):
        def invoke(action):
            def run():
                time.sleep(delay)
                action()
            threading.Thread(target=run, daemon=True).start()
        self.bridge.Rhino.RhinoApp.InvokeOnUiThread.side_effect = invoke

    def test_health_check_and_unknown(self):
        self.assertEqual(self.bridge.process_command({"type": "test"})["status"], "success")
        self.assertEqual(self.bridge.process_command({"type": "nope"}),
                         {"status": "error", "result": "Unknown command"})

    def test_execute_code_returns_result(self):
        res = self.bridge.process_command({"type": "execute_code", "code": u"result = u'日本語'"})
        self.assertEqual(res, {"status": "success", "result": u"日本語"})
        res = self.bridge.process_command({"type": "execute_code", "code": "raise ValueError('bad')"})
        self.assertEqual(res, {"status": "error", "result": "bad"})

    def test_clear_canvas_requires_confirm(self):
        self.bridge._clear_canvas_ui = lambda: self.ui_calls.append("clear") or {"status": "success"}
        self._ui_thread()
        self.assertEqual(self.bridge.process_command({"type": "clear_canvas"})["status"], "error")
        self.assertEqual(self.ui_calls, [])
        self.assertEqual(self.bridge.process_command({"type": "clear_canvas", "confirm": True})["status"], "success")
        self.assertEqual(self.ui_calls, ["clear"])

    def test_ui_command_runs_via_ui_thread(self):
        def create(name, x, y):
            self.ui_calls.append((name, x, y, threading.current_thread().name))
            return {"status": "success", "result": {"name": name}}
        self.bridge._create_component_ui = create
        self._ui_thread()
        res = self.bridge.process_command({"type": "create_component", "name": "Panel", "x": 1, "y": 2})
        self.assertEqual(res, {"status": "success", "result": {"name": "Panel"}})
        self.assertEqual(self.ui_calls[0][:3], ("Panel", 1, 2))
        self.assertNotEqual(self.ui_calls[0][3], threading.current_thread().name)

    def test_ui_command_exception_becomes_error(self):
        def fail(*args):
            raise RuntimeError("ui failed")
        self.bridge._delete_objects_ui = fail
        self._ui_thread()
        self.assertEqual(self.bridge.process_command({"type": "delete_objects", "object_ids": ["a"]}),
                         {"status": "error", "result": "ui failed"})

    @unittest.expectedFailure
    def test_known_issue_ui_timeout_still_runs_the_command(self):
        """既知の問題: UI スレッドが 5 秒以内に応答しないと「UI action timed out」の
        エラーを返すが、その後も操作は実行される。エラーと思って再実行すると二重実行になる。"""
        self.bridge._delete_objects_ui = lambda ids: self.ui_calls.append(ids) or {"status": "success"}
        self._ui_thread(delay=5.5)
        res = self.bridge.process_command({"type": "delete_objects", "object_ids": ["a"]})
        self.assertEqual(res["result"], "UI action timed out")
        time.sleep(1.0)
        self.assertEqual(self.ui_calls, [], "the command ran after the timeout was reported")


if __name__ == "__main__":
    unittest.main()
