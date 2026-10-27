# -*- coding: utf-8 -*-
"""Tests for the client handling in rhino_scripts/rhino_mcp_bridge.py.

The bridge normally runs inside Rhino (IronPython 2.7). Here it is loaded in
CPython with Rhino/.NET modules replaced by stubs, without starting the server
and without writing to the user's RhinoMCP log folder.
Run with:  python -m unittest discover -s tests -v

Limitation: IronPython-specific socket behaviour (every recv() failure is
reported as errno 10022) is imitated by FakeClient, not exercised for real.
"""
import builtins
import json
import os
import shutil
import socket
import sys
import tempfile
import threading
import time
import types
import unittest
from unittest import mock

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
BRIDGE_PATH = os.path.join(ROOT, "rhino_scripts", "rhino_mcp_bridge.py")


class IdleEvent(object):
    """Imitates RhinoApp.Idle: handlers run on a separate 'UI' thread."""

    def __init__(self):
        self.handlers = []
        self.lock = threading.Lock()
        self.ui_thread_names = []

    def __iadd__(self, handler):
        with self.lock:
            self.handlers.append(handler)
        return self

    def __isub__(self, handler):
        with self.lock:
            if handler in self.handlers:
                self.handlers.remove(handler)
        return self

    def fire(self):
        with self.lock:
            handlers = list(self.handlers)
        for handler in handlers:
            self.ui_thread_names.append(threading.current_thread().name)
            handler(None, None)


def load_bridge(log_dir):
    stub_names = ["System", "System.Drawing", "System.Drawing.Imaging", "System.IO",
                  "Rhino", "scriptcontext", "rhinoscriptsyntax"]
    stubs = dict((name, mock.MagicMock(name=name)) for name in stub_names)
    with open(BRIDGE_PATH, "rb") as f:
        source = f.read().decode("utf-8")
    # Do not create or start the server at import time
    source = source.split("\n# Create and start server")[0]
    module = types.ModuleType("rhino_mcp_bridge_under_test")
    with mock.patch.dict(sys.modules, stubs):
        exec(compile(source, BRIDGE_PATH, "exec"), module.__dict__)
    module.get_log_dir = lambda: log_dir
    module.Rhino.RhinoApp.Idle = IdleEvent()
    return module


class FakeClient(object):
    """A client socket whose recv() blocks until data is queued.

    Like IronPython, any recv() on a closed socket raises errno 10022.
    """

    def __init__(self, chunks=None, send_error=None):
        self.chunks = list(chunks or [])
        self.cond = threading.Condition()
        self.sent = []
        self.send_error = send_error
        self.closed = False
        self.recv_after_close = 0
        self.closed_by = None

    def setsockopt(self, *args):
        pass

    def push(self, data):
        with self.cond:
            self.chunks.append(data)
            self.cond.notify_all()

    def recv(self, size):
        with self.cond:
            while True:
                if self.closed:
                    self.recv_after_close += 1
                    raise socket.error(10022, "not connected")
                if self.chunks:
                    item = self.chunks.pop(0)
                    if isinstance(item, Exception):
                        raise item
                    return item
                self.cond.wait(0.05)

    def sendall(self, data):
        if self.send_error:
            raise self.send_error
        self.sent.append(data)

    def close(self):
        with self.cond:
            self.closed = True
            self.closed_by = threading.current_thread().name
            self.cond.notify_all()


class BridgeClientTests(unittest.TestCase):
    def setUp(self):
        self.builtins_patch = mock.patch.object(builtins, "unicode", str, create=True)
        self.builtins_patch.start()
        self.log_dir = tempfile.mkdtemp(prefix="rhino_mcp_test_")
        self.bridge = load_bridge(self.log_dir)
        self.server = self.bridge.RhinoMCPServer("127.0.0.1", 0)
        self.server.running = True
        self.executed = []

        def execute_command(command):
            self.executed.append((command.get("type"), threading.current_thread().name))
            if command.get("type") == "get_server_status":
                return {"status": "success", "headless": False}
            return {"status": "success", "layer": u"レイヤー_日本語"}

        self.server.execute_command = execute_command
        self.idle = self.bridge.Rhino.RhinoApp.Idle
        self.ui_running = True
        self.ui_thread = threading.Thread(target=self._ui_loop, name="ui-thread", daemon=True)
        self.ui_thread.start()

    def tearDown(self):
        self.ui_running = False
        self.server.running = False
        self.ui_thread.join(1)
        self.builtins_patch.stop()
        shutil.rmtree(self.log_dir, ignore_errors=True)

    def _ui_loop(self):
        while self.ui_running:
            self.idle.fire()
            time.sleep(0.01)

    def _run_handler(self, client):
        worker = threading.Thread(target=self.server._handle_client, args=(client,), name="worker")
        worker.start()
        return worker

    def _rhino_lines(self):
        return [str(c.args[0]) for c in self.bridge.Rhino.RhinoApp.WriteLine.call_args_list]

    def _log_text(self):
        path = os.path.join(self.log_dir, "rhino_mcp.log")
        if not os.path.exists(path):
            return ""
        with open(path, "rb") as f:
            return f.read().decode("utf-8", "replace")

    def test_command_runs_on_ui_thread_and_japanese_response_is_sent(self):
        payload = json.dumps({"type": "get_layers", "params": {}}).encode("utf-8")
        client = FakeClient([payload, b""])
        worker = self._run_handler(client)
        worker.join(3)
        self.assertFalse(worker.is_alive())
        self.assertEqual(self.executed, [("get_layers", "ui-thread")])
        response = json.loads(b"".join(client.sent).decode("utf-8"))
        self.assertEqual(response["layer"], u"レイヤー_日本語")
        self.assertEqual(self.idle.handlers, [])
        self.assertEqual(client.closed_by, "worker")

    def test_command_split_across_recv_calls_with_japanese(self):
        payload = json.dumps({"type": "execute_code", "params": {"code": u"name = 'テスト'"}},
                             ensure_ascii=False).encode("utf-8")
        cut = payload.index(u"テ".encode("utf-8")) + 1   # inside a multi-byte character
        client = FakeClient([payload[:cut], payload[cut:], b""])
        worker = self._run_handler(client)
        worker.join(3)
        self.assertEqual(self.executed, [("execute_code", "ui-thread")])
        self.assertEqual(len(client.sent), 1)

    def test_send_failure_closes_on_worker_without_recv_after_close(self):
        """The original bug: the UI thread closed the socket while recv() was pending."""
        payload = json.dumps({"type": "execute_code", "params": {"code": "pass"}}).encode("utf-8")
        client = FakeClient([payload], send_error=socket.error(10054, "reset"))
        worker = self._run_handler(client)
        worker.join(3)
        self.assertFalse(worker.is_alive())
        self.assertEqual(self.executed, [("execute_code", "ui-thread")])
        self.assertEqual(client.recv_after_close, 0)
        self.assertEqual(client.closed_by, "worker")
        lines = self._rhino_lines()
        self.assertEqual(sum(1 for l in lines if u"結果を返せませんでした" in l), 1)
        self.assertFalse(any("Error handling client" in l for l in lines))

    def test_client_disconnect_while_waiting_is_quiet(self):
        client = FakeClient([socket.error(10022, u"ソケットが接続されていないか")])
        worker = self._run_handler(client)
        worker.join(3)
        self.assertFalse(worker.is_alive())
        self.assertEqual(self._rhino_lines(), [])
        self.assertIn("Client connection closed while waiting", self._log_text())

    def test_normal_disconnect_is_silent(self):
        worker = self._run_handler(FakeClient([b""]))
        worker.join(3)
        self.assertEqual(self._rhino_lines(), [])

    def test_status_command_does_not_wait_for_ui_thread(self):
        self.ui_running = False
        self.ui_thread.join(1)
        payload = json.dumps({"type": "get_server_status"}).encode("utf-8")
        client = FakeClient([payload, b""])
        worker = self._run_handler(client)
        worker.join(3)
        self.assertEqual(self.executed, [("get_server_status", "worker")])
        self.assertEqual(json.loads(client.sent[0].decode("utf-8"))["status"], "success")

    def test_non_object_json_gets_error_response(self):
        client = FakeClient([b"[1, 2]", b""])
        worker = self._run_handler(client)
        worker.join(3)
        self.assertEqual(self.executed, [])
        self.assertEqual(json.loads(client.sent[0].decode("utf-8"))["status"], "error")

    def test_unexpected_error_is_reported(self):
        client = FakeClient([RuntimeError("boom")])
        worker = self._run_handler(client)
        worker.join(3)
        self.assertTrue(any("Error handling client: boom" in l for l in self._rhino_lines()))

    def test_stop_while_waiting_for_ui_does_not_run_command_later(self):
        self.ui_running = False
        self.ui_thread.join(1)
        payload = json.dumps({"type": "execute_code", "params": {"code": "pass"}}).encode("utf-8")
        client = FakeClient([payload])
        worker = self._run_handler(client)
        time.sleep(0.2)
        self.server.running = False
        worker.join(3)
        self.assertFalse(worker.is_alive())
        self.assertEqual(self.idle.handlers, [])
        self.assertEqual(self.executed, [])


if __name__ == "__main__":
    unittest.main()
