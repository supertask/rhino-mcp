# -*- coding: utf-8 -*-
"""Tests for individual commands in rhino_scripts/rhino_mcp_bridge.py.

The bridge is loaded in CPython with Rhino modules mocked; the document is a
small fake shaped like Rhino 7's (for example, Layer has no ObjectCount).
Run with:  python -m unittest discover -s tests -v
"""
import json
import os
import shutil
import tempfile
import types
import unittest
from unittest import mock

from helpers import stubs


def layer(index, name, deleted=False):
    # Only the attributes Rhino 7's Layer really has (no ObjectCount)
    return types.SimpleNamespace(Index=index, Name=name, IsVisible=True, IsLocked=False,
                                 IsDeleted=deleted, FullPath=name)


def rhino_object(layer_index, object_id):
    return types.SimpleNamespace(Id=object_id, Attributes=types.SimpleNamespace(LayerIndex=layer_index))


class BridgeCommandTestCase(unittest.TestCase):
    def setUp(self):
        self.builtins_patch = stubs.py2_builtins()
        self.builtins_patch.__enter__()
        self.log_dir = tempfile.mkdtemp(prefix="rhino_mcp_test_")
        self.bridge = stubs.load_bridge("rhino_mcp_bridge.py", log_dir=self.log_dir,
                                        cut_marker="\n# Create and start server")
        self.server = self.bridge.RhinoMCPServer("127.0.0.1", 0)

    def tearDown(self):
        self.builtins_patch.__exit__(None, None, None)
        shutil.rmtree(self.log_dir, ignore_errors=True)


class GetLayersTests(BridgeCommandTestCase):
    def test_counts_objects_per_layer_without_object_count(self):
        self.bridge.sc.doc = types.SimpleNamespace(
            Layers=[layer(0, "Default"), layer(1, u"塔の家"), layer(2, u"空のレイヤー"), layer(3, "old", deleted=True)],
            Objects=[rhino_object(1, "a"), rhino_object(1, "b"), rhino_object(0, "c")])
        res = self.server._get_layers()
        self.assertEqual(res["status"], "success", res)
        self.assertEqual([(l["name"], l["object_count"]) for l in res["layers"]],
                         [("Default", 1), (u"塔の家", 2), (u"空のレイヤー", 0)])

    def test_dispatch_through_execute_command(self):
        # execute_command works on Rhino's active document
        self.bridge.Rhino.RhinoDoc.ActiveDoc = types.SimpleNamespace(Layers=[layer(0, "Default")], Objects=[])
        res = self.server.execute_command({"type": "get_layers"})
        self.assertEqual(res["layers"][0]["object_count"], 0)


class ScriptContextDocTests(BridgeCommandTestCase):
    """GhPython switches the shared scriptcontext.doc to the Grasshopper document."""

    def test_commands_run_on_the_rhino_document(self):
        rhino_doc = types.SimpleNamespace(Layers=[layer(0, "Default")], Objects=[rhino_object(0, "a")])
        self.bridge.Rhino.RhinoDoc.ActiveDoc = rhino_doc
        self.bridge.sc.doc = "GrasshopperDocument"   # left behind by a GhPython solve
        res = self.server.execute_command({"type": "get_layers"})
        self.assertEqual(res["status"], "success", res)
        self.assertIs(self.bridge.sc.doc, rhino_doc)
        self.assertEqual(res["layers"][0]["object_count"], 1)

    def test_execute_code_sees_the_rhino_document(self):
        rhino_doc = types.SimpleNamespace(Name="rhino")
        self.bridge.Rhino.RhinoDoc.ActiveDoc = rhino_doc
        self.bridge.sc.doc = "GrasshopperDocument"
        # Code runs with the bridge's globals, where `sc` is scriptcontext
        res = self.server.execute_command({"type": "execute_code", "params": {"code": "result = sc.doc.Name"}})
        self.assertEqual(res["status"], "success", res)
        self.assertEqual(res["result"], "rhino")

    def test_status_command_does_not_touch_the_document(self):
        self.bridge.Rhino.RhinoDoc.ActiveDoc = types.SimpleNamespace()
        self.bridge.sc.doc = "GrasshopperDocument"
        self.server.execute_command({"type": "get_server_status"})
        self.assertEqual(self.bridge.sc.doc, "GrasshopperDocument")


class ExecuteCodeScopeTests(BridgeCommandTestCase):
    """Functions in AI-written code must see the code's own top-level names."""

    CODE = (u"W, D = 7.9, 13.5\n"
            u"def half(v):\n"
            u"    return v / 2.0\n"
            u"def area():\n"
            u"    return W * D\n"          # uses top-level names
            u"def summary():\n"
            u"    return u'{0} / {1}'.format(half(W), area())\n"   # calls another helper
            u"result = summary()\n")

    def run_code(self, code):
        return self.server.execute_command({"type": "execute_code", "params": {"code": code}})

    def test_functions_see_top_level_names(self):
        res = self.run_code(self.CODE)
        self.assertEqual(res["status"], "success", res)
        self.assertEqual(res["result"], u"3.95 / 106.65")

    def test_reports_only_new_names_and_keeps_bridge_globals_clean(self):
        res = self.run_code(self.CODE)
        self.assertEqual(sorted(res["variables"]), ["D", "W", "area", "half", "result", "summary"])
        for name in ("W", "area", "result"):
            self.assertNotIn(name, self.bridge.__dict__)

    def test_runs_are_independent(self):
        self.run_code(u"leftover = 1\nresult = 'first'")
        res = self.run_code(u"result = 'leftover' in globals()")
        self.assertEqual(res["result"], "False")

    def test_errors_are_still_reported(self):
        res = self.run_code(u"def f():\n    return undefined_name\nresult = f()")
        self.assertEqual(res["status"], "error")
        self.assertIn("undefined_name", res["message"])


class NonAsciiResponseTests(BridgeCommandTestCase):
    """Results with symbols such as the multiplication or degree sign (IronPython's json)."""

    TEXT = u"光の教会：17.7m×5.9m、方位 205°"

    def setUp(self):
        super(NonAsciiResponseTests, self).setUp()
        self.bridge.json = stubs.ironpython_json()

    def send(self, response):
        client = types.SimpleNamespace(sent=[])
        client.sendall = client.sent.append
        self.server._send_response(client, response)
        return json.loads(b"".join(client.sent).decode("utf-8"))

    def test_execute_code_with_symbols_succeeds(self):
        code = u"x = u'17×5'\nresult = u'" + self.TEXT + u"'"
        res = self.server.execute_command({"type": "execute_code", "params": {"code": code}})
        self.assertEqual(res["status"], "success", res)
        self.assertEqual(res["result"], self.TEXT)

    def test_response_with_symbols_is_sent_as_utf8(self):
        sent = self.send({"status": "success", "result": self.TEXT, "variables": {"x": u"17×5"}})
        self.assertEqual(sent["result"], self.TEXT)
        self.assertEqual(sent["variables"]["x"], u"17×5")


NETSTAT = ("  TCP    127.0.0.1:9876         0.0.0.0:0              LISTENING       {pid}\r\n"
           "  TCP    127.0.0.1:9876         127.0.0.1:50123        TIME_WAIT       0\r\n"
           "  TCP    127.0.0.1:19876        0.0.0.0:0              LISTENING       777\r\n")


class PortHolderTests(unittest.TestCase):
    """Running the bridge script while the port is busy must never close this Rhino."""

    def setUp(self):
        self.builtins_patch = stubs.py2_builtins()
        self.builtins_patch.__enter__()
        self.log_dir = tempfile.mkdtemp(prefix="rhino_mcp_test_")
        self.rhino = stubs.load_bridge("rhino_mcp_bridge.py", log_dir=self.log_dir,
                                       cut_marker="\n# Create and start server", keep_force_kill=True)
        self.gh = stubs.load_bridge("grasshopper_mcp_bridge.py", grasshopper=True, keep_force_kill=True)

    def tearDown(self):
        self.builtins_patch.__exit__(None, None, None)
        shutil.rmtree(self.log_dir, ignore_errors=True)

    def test_listening_pid_ignores_connections_and_other_ports(self):
        for bridge in (self.rhino, self.gh):
            out = NETSTAT.replace("{pid}", "4321")
            self.assertEqual(bridge.listening_pid(out, 9876), "4321")
            self.assertEqual(bridge.listening_pid(out, 19876), "777")
            self.assertIsNone(bridge.listening_pid("  TCP  127.0.0.1:9876  127.0.0.1:5  TIME_WAIT  0\r\n", 9876))

    def kill_with_netstat(self, bridge, call_kill, pid):
        popen = mock.MagicMock()
        popen.return_value.communicate.side_effect = [
            (NETSTAT.replace("{pid}", str(pid)), ""),  # IronPython returns str
            ('"Rhino.exe","%d","Console","1","150,000 K"' % pid, ""),
        ]
        with mock.patch.object(bridge.platform, "system", return_value="Windows"), \
             mock.patch.object(bridge.subprocess, "Popen", popen), \
             mock.patch.object(bridge.subprocess, "call") as call:
            killed, _ = call_kill()
        return killed, call

    def test_never_kills_this_rhino(self):
        me = os.getpid()
        server = self.rhino.RhinoMCPServer("127.0.0.1", 9876)
        for bridge, call_kill in ((self.rhino, server._force_kill_port_holder),
                                  (self.gh, self.gh._force_kill_port_holder)):
            killed, call = self.kill_with_netstat(bridge, call_kill, me)
            self.assertFalse(killed)
            call.assert_not_called()

    def test_still_kills_another_rhino(self):
        server = self.rhino.RhinoMCPServer("127.0.0.1", 9876)
        other = os.getpid() + 100000
        killed, call = self.kill_with_netstat(self.rhino, server._force_kill_port_holder, other)
        self.assertTrue(killed)
        self.assertIn(str(other), call.call_args[0][0])


class CaptureLabelTests(BridgeCommandTestCase):
    def test_annotation_label_uses_a_real_line_break(self):
        rs = self.bridge.rs
        rs.SelectedObjects.return_value = []
        rs.BoundingBox.return_value = ["p0", "p1"]
        rs.GetUserText.return_value = "27184559"
        rs.ObjectName.return_value = u"5階"
        rs.AddTextDot.return_value = "dot"
        self.bridge.sc.doc = types.SimpleNamespace(Objects=[rhino_object(0, "obj")])
        self.server._capture_single_view = lambda *args, **kwargs: {"type": "base64", "data": "x"}

        res = self.server._capture_viewport({"view": "Active"})

        self.assertEqual(res["type"], "multi_image")
        text = rs.AddTextDot.call_args[0][0]
        self.assertEqual(text, u"5階\n27184559")
        self.assertNotIn("\\n", text)
        rs.DeleteObjects.assert_called_once_with(["dot"])   # temporary labels are removed


if __name__ == "__main__":
    unittest.main()
