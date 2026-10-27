# -*- coding: utf-8 -*-
"""Tests for individual commands in rhino_scripts/rhino_mcp_bridge.py.

The bridge is loaded in CPython with Rhino modules mocked; the document is a
small fake shaped like Rhino 7's (for example, Layer has no ObjectCount).
Run with:  python -m unittest discover -s tests -v
"""
import shutil
import tempfile
import types
import unittest

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
        self.bridge.sc.doc = types.SimpleNamespace(Layers=[layer(0, "Default")], Objects=[])
        res = self.server.execute_command({"type": "get_layers"})
        self.assertEqual(res["layers"][0]["object_count"], 0)


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
