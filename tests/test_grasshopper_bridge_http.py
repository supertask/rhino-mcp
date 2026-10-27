# -*- coding: utf-8 -*-
"""Tests for the request handling in rhino_scripts/grasshopper_mcp_bridge.py.

The bridge's real server_loop() runs in CPython on an ephemeral port (not
9999), with Rhino/Grasshopper modules mocked. The parts that talk to the
Grasshopper API are replaced by fakes; only HTTP handling and the generic
parts of process_command() are tested.
Run with:  python -m unittest discover -s tests -v

Limitation: runs on CPython, not IronPython 2.7.
"""
import json
import socket
import struct
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
            if cmd.get("type") == "slow":
                time.sleep(0.8)
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

    def _assert_quiet_and_still_serving(self):
        time.sleep(0.5)
        self.assertEqual(self.lines(), [])
        _, data, _ = http_post(self.port, b'{"type": "echo", "text": "after"}')
        self.assertEqual(json.loads(data.decode("utf-8"))["result"], u"受信: after")

    def test_empty_connection_is_quiet(self):
        """何も送らずに閉じた接続（接続確認など）で、画面にエラーを出さない。"""
        http_post(self.port, b'{"type": "echo"}')
        self.bridge.Rhino.RhinoApp.WriteLine.reset_mock()
        socket.create_connection(("127.0.0.1", self.port), timeout=1).close()
        self._assert_quiet_and_still_serving()
        self.assertEqual([c["type"] for c in self.received], ["echo", "echo"])

    def test_disconnect_in_the_middle_of_the_body(self):
        """本文の途中で切れても、ブリッジが止まらずコマンドも実行しない。"""
        s = socket.create_connection(("127.0.0.1", self.port), timeout=5)
        s.sendall(b"POST / HTTP/1.1\r\nContent-Length: 100\r\n\r\n{\"type\": \"ec")
        time.sleep(0.2)
        s.close()
        self._assert_quiet_and_still_serving()
        self.assertEqual([c["text"] for c in self.received], ["after"])

    def test_client_gone_before_response_is_quiet(self):
        """クライアントが待ちきれずに切断し、返事を送れなかった場合も画面に出さない。"""
        s = socket.create_connection(("127.0.0.1", self.port), timeout=5)
        body = b'{"type": "slow"}'
        s.sendall(b"POST / HTTP/1.1\r\nContent-Length: %d\r\n\r\n%s" % (len(body), body))
        time.sleep(0.2)
        s.setsockopt(socket.SOL_SOCKET, socket.SO_LINGER, struct.pack("ii", 1, 0))
        s.close()
        time.sleep(1.0)   # the bridge finishes the command and tries to answer
        self._assert_quiet_and_still_serving()

    def test_reset_connection_is_quiet(self):
        s = socket.create_connection(("127.0.0.1", self.port), timeout=5)
        s.sendall(b"POST / HTTP/1.1\r\nContent-Length: 100\r\n\r\n{")
        s.setsockopt(socket.SOL_SOCKET, socket.SO_LINGER, struct.pack("ii", 1, 0))
        s.close()
        self._assert_quiet_and_still_serving()


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

    def test_execute_code_functions_see_top_level_names(self):
        code = (u"N = 12\n"
                u"def rods():\n"
                u"    return [i for i in range(N)]\n"
                u"result = u'本数: {0}'.format(len(rods()))")
        res = self.bridge.process_command({"type": "execute_code", "code": code})
        self.assertEqual(res, {"status": "success", "result": u"本数: 12"})
        self.assertNotIn("N", self.bridge.__dict__)

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

    def test_update_script_waits_for_the_ui_thread(self):
        """update_script は UI スレッドで書き換えが終わるのを待ち、本当の結果を返す。"""
        def update(guid, code, description, message_to_user, param_definitions):
            time.sleep(0.3)
            self.ui_calls.append((guid, code, description, message_to_user, param_definitions))
            return {"status": "success", "result": "Updated successfully"}
        self.bridge._update_script_component_on_ui_thread = update
        self._ui_thread(delay=0.1)
        params = [{"type": "input", "name": "x"}]
        res = self.bridge.process_command({"type": "update_script", "instance_guid": "g", "code": "result = 1",
                                           "description": "d", "message_to_user": "m", "param_definitions": params})
        self.assertEqual(res, {"status": "success", "result": "Updated successfully"})
        self.assertEqual(self.ui_calls, [("g", "result = 1", "d", "m", params)])

    def test_update_script_error_is_returned(self):
        self.bridge._update_script_component_on_ui_thread = lambda *a: {"status": "error", "result": "Target not found"}
        self._ui_thread()
        res = self.bridge.process_command({"type": "update_script", "instance_guid": "g"})
        self.assertEqual(res, {"status": "error", "result": "Target not found"})

    def test_update_script_with_code_reference_waits_for_the_ui_thread(self):
        def update(guid, file_path, param_definitions, description, name, force):
            time.sleep(0.3)
            self.ui_calls.append((guid, file_path, name, force))
            return {"status": "success", "result": "Updated Ref"}
        self.bridge._update_code_ref_ui = update
        self._ui_thread(delay=0.1)
        res = self.bridge.process_command({"type": "update_script_with_code_reference", "instance_guid": "g",
                                           "file_path": "C:/x.py", "name": "Tool", "force_code_reference": True})
        self.assertEqual(res, {"status": "success", "result": "Updated Ref"})
        self.assertEqual(self.ui_calls, [("g", "C:/x.py", "Tool", True)])

    def test_update_script_not_started_in_time_is_cancelled(self):
        self._use_short_ui_timeouts()
        self.bridge._update_script_component_on_ui_thread = lambda *a: self.ui_calls.append(a) or {"status": "success"}
        self._ui_thread(delay=0.6)
        res = self.bridge.process_command({"type": "update_script", "instance_guid": "g", "code": "x"})
        self.assertEqual(res["result"], self.bridge.UI_NOT_STARTED_MESSAGE)
        time.sleep(0.8)
        self.assertEqual(self.ui_calls, [])

    def _use_short_ui_timeouts(self):
        self.bridge.UI_START_TIMEOUT = 0.3
        self.bridge.UI_RUN_TIMEOUT = 0.6

    def test_command_not_started_in_time_is_cancelled(self):
        """UI スレッドが空かずに始まらなかった操作は取り消され、あとで実行されない。"""
        self._use_short_ui_timeouts()
        self.bridge._delete_objects_ui = lambda ids: self.ui_calls.append(ids) or {"status": "success"}
        self._ui_thread(delay=0.6)
        res = self.bridge.process_command({"type": "delete_objects", "object_ids": ["a"]})
        self.assertEqual(res, {"status": "error", "result": self.bridge.UI_NOT_STARTED_MESSAGE})
        self.assertIn(u"実行されていません", res["result"])
        time.sleep(0.8)   # the UI thread becomes free later
        self.assertEqual(self.ui_calls, [])

    def test_started_command_is_waited_for(self):
        """始まった操作は、開始の待ち時間を過ぎても最後まで待って結果を返す。"""
        self._use_short_ui_timeouts()

        def slow_delete(ids):
            time.sleep(0.4)
            self.ui_calls.append(ids)
            return {"status": "success", "result": "deleted"}
        self.bridge._delete_objects_ui = slow_delete
        self._ui_thread(delay=0.1)
        res = self.bridge.process_command({"type": "delete_objects", "object_ids": ["a"]})
        self.assertEqual(res, {"status": "success", "result": "deleted"})
        self.assertEqual(self.ui_calls, [["a"]])

    def test_long_running_command_is_result_unknown_and_runs_once(self):
        """長引いた操作は「結果不明」と返し、操作自体は 1 回だけ実行される。"""
        self._use_short_ui_timeouts()

        def very_slow_delete(ids):
            time.sleep(1.0)
            self.ui_calls.append(ids)
            return {"status": "success"}
        self.bridge._delete_objects_ui = very_slow_delete
        self._ui_thread()
        res = self.bridge.process_command({"type": "delete_objects", "object_ids": ["a"]})
        self.assertEqual(res, {"status": "error", "result": self.bridge.UI_RESULT_UNKNOWN_MESSAGE})
        self.assertIn(u"実行されたかは不明", res["result"])
        time.sleep(1.0)
        self.assertEqual(self.ui_calls, [["a"]])


if __name__ == "__main__":
    unittest.main()
