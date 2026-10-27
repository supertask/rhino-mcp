# -*- coding: utf-8 -*-
"""Tests for the MCP-side Rhino connection (src/rhino_mcp/rhino_tools.py).

A fake Rhino bridge runs on an ephemeral localhost port, so neither Rhino nor
port 9876 is touched. Run with:  python -m unittest discover -s tests -v
"""
import time
import unittest

from helpers import stubs
from helpers.fake_servers import JP_LAYER, FakeRhino

stubs.use_src()
stubs.install_optional_stubs()

from rhino_mcp import rhino_tools  # noqa: E402
from rhino_mcp.rhino_tools import (  # noqa: E402
    RhinoCommandError,
    RhinoConnection,
    RhinoConnectionError,
    RhinoResultUnknownError,
)


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
        self.tools = rhino_tools.RhinoTools(stubs.new_app())

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
