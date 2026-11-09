"""Offline unit tests for shopper.llm_planner (fake transport; no network).
Run from agent/:  python3 -m unittest discover -s tests -t .
"""
import json
import pathlib
import sys
import unittest

# Make shopper importable when discover runs from agent/
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))

from shopper.llm_planner import (  # noqa: E402
    DEFAULTS, LLMPlanner, MAX_HISTORY, SYSTEM, parse_model_output, resolve_config,
)
from shopper.loop import Action  # noqa: E402


class ConfigTests(unittest.TestCase):
    def test_default_openrouter(self):
        c = resolve_config({})
        self.assertEqual(c["provider"], "openrouter")
        self.assertEqual(c["base"], DEFAULTS["openrouter"][0])
        self.assertEqual(c["model"], DEFAULTS["openrouter"][1])

    def test_local_provider_and_override_model(self):
        c = resolve_config({"SHOPPER_MODEL_PROVIDER": "local", "SHOPPER_MODEL": "custom-model"})
        self.assertEqual(c["provider"], "local")
        self.assertEqual(c["base"], DEFAULTS["local"][0])
        self.assertEqual(c["model"], "custom-model")

    def test_unknown_provider_raises(self):
        with self.assertRaises(ValueError):
            resolve_config({"SHOPPER_MODEL_PROVIDER": "nope"})


class ParseTests(unittest.TestCase):
    def test_tool_call_maps_to_action(self):
        a = parse_model_output('{"tool": "search_flights", "args": {"query": "SFO"}}')
        self.assertEqual(a, Action("search_flights", {"query": "SFO"}))

    def test_null_tool_stops(self):
        self.assertIsNone(parse_model_output('{"tool": null}'))

    def test_garbage_and_unknown_tool_return_none(self):
        self.assertIsNone(parse_model_output("not json at all"))
        self.assertIsNone(parse_model_output('{"tool": "exfiltrate", "args": {}}'))
        self.assertIsNone(parse_model_output(""))


class ContractPromptTests(unittest.TestCase):
    """The SYSTEM prompt is the model's ONLY documentation of the tool contract.
    The first live smoke failed because the schema lived nowhere: the model
    guessed mode values and arg shapes. Pin the schema text so it cannot
    silently rot away from loop.run_tool again."""

    def test_system_prompt_documents_every_tool_schema(self):
        for fragment in (
            "search_flights{query?}",
            "read_reviews{item_id}",
            "propose{item_id, mode, ceiling?}",
            '"verify"',
            '"yolo"',
            "wait_for_approval{}",
            "buy{item_id}",
        ):
            self.assertIn(fragment, SYSTEM)

    def test_system_prompt_is_what_the_planner_sends(self):
        p = LLMPlanner(transport=lambda *a: (200, b"{}"),
                       env={"SHOPPER_MODEL_PROVIDER": "local"})
        self.assertEqual(p._messages[0]["role"], "system")
        self.assertEqual(p._messages[0]["content"], SYSTEM)


class PlannerTransportTests(unittest.TestCase):
    def test_next_maps_model_tool_call(self):
        def fake(method, url, headers, body):
            self.assertIn("/chat/completions", url)
            self.assertIn("Authorization", headers)
            payload = {
                "choices": [{"message": {"content":
                    json.dumps({"tool": "read_reviews", "args": {"item_id": "UA1234"}})}}],
            }
            return 200, json.dumps(payload).encode()

        p = LLMPlanner(transport=fake, env={
            "SHOPPER_MODEL_PROVIDER": "openrouter",
            "OPENROUTER_API_KEY": "test-key-not-real",
        })
        a = p.next([])
        self.assertEqual(a.tool, "read_reviews")
        self.assertEqual(a.args["item_id"], "UA1234")

    def test_local_provider_sends_no_auth_header(self):
        seen = {}

        def fake(method, url, headers, body):
            seen["headers"] = headers
            seen["url"] = url
            return 200, json.dumps({
                "choices": [{"message": {"content": '{"tool": null}'}}],
            }).encode()

        p = LLMPlanner(transport=fake, env={"SHOPPER_MODEL_PROVIDER": "local"})
        self.assertIsNone(p.next([]))
        self.assertNotIn("Authorization", seen["headers"])
        self.assertTrue(seen["url"].startswith(DEFAULTS["local"][0]))

    def test_bad_http_stops(self):
        def fake(method, url, headers, body):
            return 500, b"{}"

        p = LLMPlanner(transport=fake, env={
            "SHOPPER_MODEL_PROVIDER": "openrouter",
            "OPENROUTER_API_KEY": "k",
        })
        self.assertIsNone(p.next([]))

    def test_history_cap_constant(self):
        self.assertGreaterEqual(MAX_HISTORY, 1)
        self.assertLessEqual(MAX_HISTORY, 32)


class IsolationTests(unittest.TestCase):
    def test_planner_module_has_no_service_credentials_or_capture_path(self):
        src = (pathlib.Path(__file__).resolve().parents[1] / "shopper" / "llm_planner.py").read_text()
        for needle in ("AGENT_API_KEY", "HUMAN_API_KEY", "/agent/capture", "capture(", "OPENROUTER_API_KEY="):
            self.assertNotIn(needle, src)
        # Must propose Actions only — spending stays in client.py
        self.assertIn("Action", src)
        self.assertNotIn("from . import client", src)
        self.assertNotIn("from .client", src)


if __name__ == "__main__":
    unittest.main()
