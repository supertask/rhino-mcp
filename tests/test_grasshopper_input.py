# -*- coding: utf-8 -*-
"""Tests for the helpers that repair JSON-like input written by an AI
(preprocess_llm_input / sanitize_json / extract_payload_fields in
src/rhino_mcp/grasshopper_tools.py).
Run with:  python -m unittest discover -s tests -v
"""
import unittest

from helpers import stubs

stubs.use_src()
stubs.install_optional_stubs()

try:
    from rhino_mcp import grasshopper_tools as gt
except ImportError:  # pragma: no cover - depends on the environment
    gt = None


@unittest.skipIf(gt is None, "requests is not installed")
class PreprocessTests(unittest.TestCase):
    def test_non_string_is_returned_unchanged(self):
        self.assertEqual(gt.preprocess_llm_input(5), 5)
        self.assertIsNone(gt.preprocess_llm_input(None))

    def test_backticks_become_double_quotes(self):
        self.assertEqual(gt.preprocess_llm_input("`{`a`: `b`}`"), '{"a": "b"}')

    def test_python_literals_become_json(self):
        self.assertEqual(gt.preprocess_llm_input('{"a": True, "b": False, "c": None}'),
                         '{"a": true, "b": false, "c": null}')

    def test_valid_json_is_unchanged(self):
        text = u'{"name": "円", "n": 1, "ok": true}'
        self.assertEqual(gt.preprocess_llm_input(text), text)


@unittest.skipIf(gt is None, "requests is not installed")
class SanitizeJsonTests(unittest.TestCase):
    def test_dict_is_copied(self):
        original = {"a": 1}
        result = gt.sanitize_json(original)
        self.assertEqual(result, original)
        self.assertIsNot(result, original)

    def test_markdown_code_fence_is_removed(self):
        self.assertEqual(gt.sanitize_json('```json\n{"a": 1}\n```'), {"a": 1})
        self.assertEqual(gt.sanitize_json('  ```\n{"a": 1}\n```  '), {"a": 1})

    def test_markdown_code_fence_around_backtick_object(self):
        self.assertEqual(gt.sanitize_json("```json\n{`a`: `b`}\n```"), {"a": "b"})

    def test_backtick_object(self):
        self.assertEqual(gt.sanitize_json("`{`instance_guid`: `abc`, `ok`: True}`"),
                         {"instance_guid": "abc", "ok": True})

    def test_japanese(self):
        self.assertEqual(gt.sanitize_json(u'{"description": "円を作る"}'), {"description": u"円を作る"})

    def test_newlines_outside_strings_are_tolerated(self):
        self.assertEqual(gt.sanitize_json('{\n  "code": "result = 1",\n  "n": 2\n}'),
                         {"code": "result = 1", "n": 2})

    def test_garbage_gives_empty_dict(self):
        self.assertEqual(gt.sanitize_json("not json at all"), {})
        self.assertEqual(gt.sanitize_json(123), {})


@unittest.skipIf(gt is None, "requests is not installed")
class ExtractPayloadFieldsTests(unittest.TestCase):
    def test_valid_json(self):
        self.assertEqual(gt.extract_payload_fields('{"instance_guid": "g", "code": "x = 1"}'),
                         {"instance_guid": "g", "code": "x = 1"})

    def test_raw_newlines_inside_code_are_recovered(self):
        # Not valid JSON (literal newlines inside a string), as an AI sometimes writes it
        raw = '{"instance_guid": "g", "code": "a = 1\nresult = a", "message_to_user": "done"}'
        self.assertEqual(gt.extract_payload_fields(raw),
                         {"instance_guid": "g", "code": "a = 1\nresult = a", "message_to_user": "done"})

    def test_non_string(self):
        self.assertEqual(gt.extract_payload_fields(None), {})

    def test_unrelated_text(self):
        self.assertEqual(gt.extract_payload_fields("hello"), {})


if __name__ == "__main__":
    unittest.main()
