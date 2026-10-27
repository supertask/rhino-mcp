# -*- coding: utf-8 -*-
"""Tests for each Rhino MCP tool (src/rhino_mcp/rhino_tools.py: RhinoTools).

Checks which command each tool sends and how it turns the reply into tool
output. A fake Rhino bridge is used; Rhino itself is not needed.
Run with:  python -m unittest discover -s tests -v
"""
import base64
import json
import unittest

from helpers import stubs
from helpers.fake_servers import JP_LAYER, FakeRhino

stubs.use_src()
stubs.install_optional_stubs()

from rhino_mcp import rhino_tools  # noqa: E402
from rhino_mcp.rhino_tools import RhinoConnection  # noqa: E402

JPEG_BYTES = b"\xff\xd8\xff\xe0fake-jpeg"
JPEG_B64 = base64.b64encode(JPEG_BYTES).decode("ascii")


class RhinoToolsTestCase(unittest.TestCase):
    def setUp(self):
        self.rhino = FakeRhino()
        self._saved = rhino_tools._rhino_connection
        rhino_tools._rhino_connection = RhinoConnection(host="127.0.0.1", port=self.rhino.port)
        self.tools = rhino_tools.RhinoTools(stubs.new_app())

    def tearDown(self):
        rhino_tools._rhino_connection.disconnect()
        rhino_tools._rhino_connection = self._saved
        self.rhino.close()


class SceneToolsTests(RhinoToolsTestCase):
    def test_get_scene_info(self):
        self.rhino.responses["get_scene_info"] = {
            "status": "success", "layers": [{"full_path": JP_LAYER, "object_count": 2}]}
        out = json.loads(self.tools.get_scene_info(None))
        self.assertEqual(out["layers"][0]["full_path"], JP_LAYER)
        self.assertEqual(self.rhino.last_payload("get_scene_info")["params"], {})

    def test_get_layers(self):
        self.rhino.responses["get_layers"] = {"status": "success", "layers": [{"name": JP_LAYER}]}
        out = json.loads(self.tools.get_layers(None))
        self.assertEqual(out["layers"][0]["name"], JP_LAYER)

    def test_get_scene_objects_with_metadata_sends_filters(self):
        self.tools.get_scene_objects_with_metadata(
            None, filters={"layer": "Wall*", "name": u"窓*"}, metadata_fields=["short_id", "bbox"])
        params = self.rhino.last_payload("get_objects_with_metadata")["params"]
        self.assertEqual(params["filters"], {"layer": "Wall*", "name": u"窓*"})
        self.assertEqual(params["metadata_fields"], ["short_id", "bbox"])

    def test_get_scene_objects_with_metadata_defaults(self):
        self.tools.get_scene_objects_with_metadata(None)
        params = self.rhino.last_payload("get_objects_with_metadata")["params"]
        self.assertEqual(params, {"filters": {}, "metadata_fields": None})

    def test_rhino_error_becomes_error_text(self):
        self.rhino.behaviour["get_scene_info"] = "error"
        out = self.tools.get_scene_info(None)
        self.assertTrue(out.startswith("Error getting scene info:"))
        self.assertIn(u"Rhino側のエラー", out)

    def test_rhino_not_running_becomes_error_text(self):
        self.rhino.close()
        out = self.tools.get_layers(None)
        self.assertIn(u"Rhinoに接続できません", out)


class CaptureViewportTests(RhinoToolsTestCase):
    def _multi_image(self, labels):
        return {"type": "multi_image",
                "images": [{"type": "base64", "media_type": "image/jpeg", "data": JPEG_B64, "label": l}
                           for l in labels]}

    def test_default_captures_and_returns_images(self):
        self.rhino.responses["capture_viewport"] = self._multi_image(["Perspective", "Top", "Front", "Right"])
        images = self.tools.capture_viewport(None)
        params = self.rhino.last_payload("capture_viewport")["params"]
        self.assertIsNone(params["view"])     # the bridge picks the 4-view default
        self.assertEqual(params["max_size"], 800)
        self.assertTrue(params["show_annotations"])
        self.assertTrue(params["zoom_extents"])
        self.assertEqual(len(images), 4)
        self.assertEqual(images[0].data, JPEG_BYTES)

    def test_all_expands_to_seven_views(self):
        self.rhino.responses["capture_viewport"] = self._multi_image(["x"] * 7)
        self.tools.capture_viewport(None, view="ALL")
        self.assertEqual(self.rhino.last_payload("capture_viewport")["params"]["view"],
                         ["Top", "Bottom", "Front", "Back", "Right", "Left", "Perspective"])

    def test_single_and_list_views_are_passed_through(self):
        self.rhino.responses["capture_viewport"] = self._multi_image(["Top"])
        self.tools.capture_viewport(None, view="Top", layer=JP_LAYER, max_size=400,
                                    show_annotations=False, zoom_extents=False)
        params = self.rhino.last_payload("capture_viewport")["params"]
        self.assertEqual(params, {"layer": JP_LAYER, "show_annotations": False, "max_size": 400,
                                  "view": "Top", "zoom_extents": False})
        self.tools.capture_viewport(None, view=["Top", "Front"])
        self.assertEqual(self.rhino.last_payload("capture_viewport")["params"]["view"], ["Top", "Front"])

    def test_old_single_image_format_is_still_accepted(self):
        self.rhino.responses["capture_viewport"] = {"type": "image", "source": {"data": JPEG_B64}}
        images = self.tools.capture_viewport(None, view="Active")
        self.assertEqual(len(images), 1)

    def test_bridge_error_raises(self):
        self.rhino.responses["capture_viewport"] = {"type": "error", "message": "no view"}
        with self.assertRaises(Exception) as ctx:
            self.tools.capture_viewport(None)
        self.assertIn("no view", str(ctx.exception))

    def test_no_images_raises(self):
        self.rhino.responses["capture_viewport"] = {"type": "multi_image", "images": []}
        with self.assertRaises(Exception):
            self.tools.capture_viewport(None)


class ExecuteRhinoCodeTests(RhinoToolsTestCase):
    def test_code_is_sent_with_metadata_helper(self):
        self.rhino.responses["execute_code"] = {"status": "success", "result": u"完了"}
        out = self.tools.execute_rhino_code(None, u"result = 'テスト'")
        self.assertEqual(out, u"完了")
        code = self.rhino.last_payload("execute_code")["params"]["code"]
        self.assertIn("def add_object_metadata(", code)
        self.assertTrue(code.endswith(u"result = 'テスト'"))
        # The helper must stay IronPython 2.7 compatible (no f-strings)
        helper = code.split("def add_object_metadata(")[1]
        self.assertNotIn('f"', helper)
        self.assertNotIn("f'", helper)

    def test_default_result_text(self):
        self.rhino.responses["execute_code"] = {"status": "success"}
        self.assertEqual(self.tools.execute_rhino_code(None, "x = 1"), "Code executed successfully")

    def test_rhino_error_is_returned_as_text(self):
        self.rhino.behaviour["execute_code"] = "error"
        out = self.tools.execute_rhino_code(None, "x = 1")
        self.assertTrue(out.startswith("Error executing code:"))
        self.assertIn(u"Rhino側のエラー", out)

    def test_tools_are_registered(self):
        app = stubs.new_app()
        registered = []
        original_tool = app.tool

        def tool():
            register = original_tool()

            def wrapper(fn):
                registered.append(fn.__name__)
                return register(fn)
            return wrapper

        app.tool = tool
        rhino_tools.RhinoTools(app)
        self.assertEqual(sorted(registered), sorted([
            "get_scene_info", "get_layers", "get_scene_objects_with_metadata",
            "capture_viewport", "execute_rhino_code"]))


if __name__ == "__main__":
    unittest.main()
