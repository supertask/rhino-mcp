# -*- coding: utf-8 -*-
"""Tests for each Grasshopper MCP tool (src/rhino_mcp/grasshopper_tools.py).

Checks which HTTP request each tool sends and how it turns the reply into
tool output. A fake Grasshopper bridge is used; Rhino is not needed.
Tests marked "既知の問題" document current behaviour that should change; they
are expected failures, so the suite stays green until the code is fixed.
Run with:  python -m unittest discover -s tests -v
"""
import json
import unittest

from helpers import stubs
from helpers.fake_servers import JP_LAYER, FakeGrasshopper, free_port

stubs.use_src()
stubs.install_optional_stubs()

try:
    import requests  # noqa: F401
    from rhino_mcp import grasshopper_tools as gt
except ImportError as e:  # pragma: no cover - depends on the environment
    gt = None
    IMPORT_ERROR = e

GUID = "a1b2c3d4-e5f6-4a5b-9c8d-7e6f5d4c3b2a"


@unittest.skipIf(gt is None, "requests is not installed")
class GrasshopperToolsTestCase(unittest.TestCase):
    def setUp(self):
        self.gh = FakeGrasshopper()
        self._saved = gt._grasshopper_connection
        gt._grasshopper_connection = gt.GrasshopperConnection(host="127.0.0.1", port=self.gh.port)
        gt._grasshopper_connection.timeout = 5.0
        self.tools = gt.GrasshopperTools(stubs.new_app())

    def tearDown(self):
        gt._grasshopper_connection = self._saved
        self.gh.close()


class ConnectionTests(GrasshopperToolsTestCase):
    def test_is_server_available(self):
        self.assertTrue(self.tools.is_server_available(None))
        self.assertEqual(self.gh.last("test"), {"type": "test", "message": "health_check"})

    def test_server_not_running(self):
        gt._grasshopper_connection = gt.GrasshopperConnection(host="127.0.0.1", port=free_port())
        self.assertFalse(self.tools.is_server_available(None))
        out = self.tools.get_canvas_stats(None)
        self.assertTrue(out.startswith("Error: HTTP request error"), out)

    def test_http_error_status(self):
        self.gh.responses["get_canvas_stats"] = 500
        out = self.tools.get_canvas_stats(None)
        self.assertTrue(out.startswith("Error: HTTP request error"), out)

    def test_bridge_error_status(self):
        self.gh.responses["get_context"] = {"status": "error", "result": "No Active Document"}
        self.assertEqual(self.tools.get_gh_context(None), "Error: No Active Document")

    def test_parameters_are_sent_flat_with_type(self):
        self.tools.get_objects(None, [GUID], simplified=True, context_depth=2)
        self.assertEqual(self.gh.last("get_objects"),
                         {"type": "get_objects", "instance_guids": [GUID], "simplified": True, "context_depth": 2})


class ExecuteCodeInGhTests(GrasshopperToolsTestCase):
    def test_plain_code_gets_default_result(self):
        self.gh.responses["execute_code"] = {"status": "success", "result": "ok"}
        self.assertEqual(self.tools.execute_code_in_gh(None, "a = 1"), "ok")
        code = self.gh.last("execute_code")["code"]
        self.assertTrue(code.startswith("a = 1"))
        self.assertIn('result = "Code executed successfully"', code)

    def test_existing_result_is_kept(self):
        self.tools.execute_code_in_gh(None, "result = 42")
        self.assertEqual(self.gh.last("execute_code")["code"], "result = 42")

    def test_trailing_return_becomes_result(self):
        self.tools.execute_code_in_gh(None, "x = 2\nreturn x * 3")
        self.assertEqual(self.gh.last("execute_code")["code"], "x = 2\nresult = x * 3")

    def test_json_payload_is_unwrapped(self):
        self.tools.execute_code_in_gh(None, json.dumps({"code": "result = 1"}))
        self.assertEqual(self.gh.last("execute_code")["code"], "result = 1")

    def test_backtick_payload_is_unwrapped(self):
        self.tools.execute_code_in_gh(None, "`{`code`: `result = 1`}`")
        self.assertEqual(self.gh.last("execute_code")["code"], "result = 1")

    def test_empty_code_is_rejected_without_request(self):
        out = self.tools.execute_code_in_gh(None, "")
        self.assertTrue(out.startswith("Error: No valid code provided"))
        self.assertEqual(self.gh.types(), [])

    def test_error_from_grasshopper(self):
        self.gh.responses["execute_code"] = {"status": "error", "result": "NameError"}
        self.assertEqual(self.tools.execute_code_in_gh(None, "result = y"), "Error: NameError")


class UpdateScriptTests(GrasshopperToolsTestCase):
    def test_requires_instance_guid(self):
        out = self.tools.update_script(None, code="result = 1")
        self.assertTrue(out.startswith("Error: No instance_guid provided"))
        self.assertEqual(self.gh.types(), [])

    def test_sends_all_fields(self):
        params = [{"type": "input", "name": "radius", "access": "item"}]
        self.tools.update_script(None, instance_guid=GUID, code="result = 1", description="d",
                                 message_to_user="m", param_definitions=params)
        self.assertEqual(self.gh.last("update_script"), {
            "type": "update_script", "instance_guid": GUID, "code": "result = 1",
            "description": "d", "message_to_user": "m", "param_definitions": params})

    def test_json_payload_in_first_argument(self):
        payload = json.dumps({"instance_guid": GUID, "code": "result = 2", "description": "desc"})
        self.tools.update_script(None, instance_guid=payload)
        sent = self.gh.last("update_script")
        self.assertEqual((sent["instance_guid"], sent["code"], sent["description"]), (GUID, "result = 2", "desc"))

    def test_string_param_definitions_are_parsed(self):
        self.tools.update_script(None, instance_guid=GUID,
                                 param_definitions=['{"type": "output", "name": "out", "optional": True}'])
        self.assertEqual(self.gh.last("update_script")["param_definitions"],
                         [{"type": "output", "name": "out", "optional": True}])

    def test_update_script_with_code_reference(self):
        self.assertTrue(self.tools.update_script_with_code_reference(None).startswith("Error: No instance_guid"))
        self.tools.update_script_with_code_reference(None, instance_guid=GUID, file_path="C:/x.py",
                                                     name="Tool", force_code_reference=True)
        sent = self.gh.last("update_script_with_code_reference")
        self.assertEqual((sent["file_path"], sent["name"], sent["force_code_reference"]), ("C:/x.py", "Tool", True))


class ComponentToolsTests(GrasshopperToolsTestCase):
    def test_simple_commands_send_expected_payloads(self):
        cases = [
            (lambda: self.tools.get_gh_context(None, simplified=True),
             {"type": "get_context", "simplified": True}),
            (lambda: self.tools.get_selected(None, context_depth=1),
             {"type": "get_selected", "simplified": False, "context_depth": 1}),
            (lambda: self.tools.expire_and_get_info(None, GUID),
             {"type": "expire_component", "instance_guid": GUID}),
            (lambda: self.tools.create_component(None, "Panel", x=10, y=20),
             {"type": "create_component", "name": "Panel", "x": 10, "y": 20}),
            (lambda: self.tools.search_components(None, u"円", limit=3),
             {"type": "search_components", "query": u"円", "limit": 3}),
            (lambda: self.tools.disconnect_components(None, GUID, "A"),
             {"type": "disconnect_components", "target_id": GUID, "target_param": "A", "source_id": None}),
            (lambda: self.tools.set_component_value(None, GUID, {"value": 10, "min": 0, "max": 100}),
             {"type": "set_component_value", "instance_guid": GUID, "value": {"value": 10, "min": 0, "max": 100}}),
            (lambda: self.tools.set_component_state(None, GUID, preview=False, wire_display="faint"),
             {"type": "set_component_state", "instance_guid": GUID, "preview": False, "enabled": None,
              "locked": None, "wire_display": "faint"}),
            (lambda: self.tools.create_group(None, [GUID], group_name=u"グループ"),
             {"type": "create_group", "component_ids": [GUID], "group_name": u"グループ"}),
            (lambda: self.tools.delete_objects(None, [GUID]),
             {"type": "delete_objects", "object_ids": [GUID]}),
            (lambda: self.tools.get_canvas_stats(None), {"type": "get_canvas_stats"}),
            (lambda: self.tools.bake_objects(None, [GUID]), {"type": "bake_objects", "object_ids": [GUID]}),
        ]
        for call, expected in cases:
            with self.subTest(command=expected["type"]):
                call()
                self.assertEqual(self.gh.requests[-1], expected)

    def test_expire_requires_guid(self):
        self.assertTrue(self.tools.expire_and_get_info(None, "").startswith("Error: No instance_guid"))
        self.assertEqual(self.gh.types(), [])

    def test_connect_components_reports_runtime_messages(self):
        self.gh.responses["connect_components"] = {
            "status": "success", "result": "Connected", "target_runtime_messages": ["Input is empty"]}
        out = self.tools.connect_components(None, GUID, "Pt", GUID, "A")
        self.assertEqual(out, "Connected. Warning/Errors: Input is empty")
        self.assertEqual(self.gh.last("connect_components"), {
            "type": "connect_components", "source_id": GUID, "source_param": "Pt",
            "target_id": GUID, "target_param": "A"})

    def test_clear_canvas_needs_confirmation_before_sending(self):
        out = self.tools.clear_canvas(None)
        self.assertTrue(out.startswith("Error: You must set confirm=True"))
        self.assertEqual(self.gh.types(), [])
        self.tools.clear_canvas(None, confirm=True)
        self.assertEqual(self.gh.last("clear_canvas"), {"type": "clear_canvas", "confirm": True})

    def test_bake_objects_formats_dict_result(self):
        self.gh.responses["bake_objects"] = {"status": "success", "result": {"baked_count": 2, "ids": ["a", "b"]}}
        self.assertEqual(self.tools.bake_objects(None, [GUID]), "Bake completed. Count: 2, IDs: ['a', 'b']")

    def test_get_available_patterns_needs_no_server(self):
        self.gh.close()
        patterns = json.loads(self.tools.get_available_patterns(None))
        self.assertIn("components", patterns)
        self.assertIn("patterns", patterns)
        self.assertTrue(any(c["name"] == "Box" for c in patterns["components"]))
        self.gh = FakeGrasshopper()   # for tearDown

    def test_all_twenty_tools_are_registered(self):
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
        gt.GrasshopperTools(app)
        self.assertEqual(len(registered), 20)


class KnownIssueTests(GrasshopperToolsTestCase):
    @unittest.expectedFailure
    def test_known_issue_japanese_is_escaped_in_output(self):
        """既知の問題: Grasshopper ツールの出力で日本語が \\uXXXX にエスケープされる
        （Rhino 側ツールは ensure_ascii=False に修正済み）。"""
        self.gh.responses["get_context"] = {"status": "success", "result": {"name": JP_LAYER}}
        self.assertIn(JP_LAYER, self.tools.get_gh_context(None))


if __name__ == "__main__":
    unittest.main()
