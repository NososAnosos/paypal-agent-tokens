"""Loop robustness: a malformed model tool call is fed back to the planner as
an error observation instead of crashing the run (the first live smoke died
on KeyError: 'item_id' / 'mode' / 'handle').
Run from agent/:  python3 -m unittest discover -s tests -t .
"""
import pathlib
import sys
import unittest

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))

from shopper.loop import Action, run  # noqa: E402


class BadThenDonePlanner:
    """Emits the exact malformed calls the live model made, then stops.
    None of them reaches the token service: each raises KeyError inside
    run_tool while reading args, before any client call, so this test
    needs no server."""

    def __init__(self):
        self.steps = [
            Action("propose", {"id": "UA1234", "price": "340.00"}),  # no item_id
            Action("propose", {"item_id": "UA1234"}),                # no mode
            Action("wait_for_approval", {}),                         # no handle yet
        ]

    def next(self, history):
        return self.steps.pop(0) if self.steps else None


class MalformedCallFeedbackTests(unittest.TestCase):
    def test_malformed_calls_become_error_observations_not_crashes(self):
        history = run(BadThenDonePlanner())
        self.assertEqual(len(history), 3)
        for step in history:
            self.assertIn("error", step["result"])
            self.assertIn("malformed tool call", step["result"]["error"])

    def test_error_names_the_missing_argument_and_the_fix(self):
        history = run(BadThenDonePlanner())
        self.assertIn("'item_id'", history[0]["result"]["error"])
        self.assertIn("'mode'", history[1]["result"]["error"])
        self.assertIn("'verify'", history[1]["result"]["error"])
        self.assertIn("'yolo'", history[1]["result"]["error"])
        self.assertIn("'handle'", history[2]["result"]["error"])


if __name__ == "__main__":
    unittest.main()
