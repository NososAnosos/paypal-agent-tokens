"""Data-driven injection harness (DEMO beat 4) against the wired offline loop.

Run from repo root:
  python3 -m unittest discover -s tests -t .
"""
import unittest

from .harness import WiredService  # noqa: F401 — sets sys.path for shopper/tokenservice
from .cases import CASES
from shopper import client
from shopper.client import ServiceError


def run_case(wired: WiredService, case: dict) -> dict:
    """Execute one data case; return step results for transcript/assertions."""
    results = {"name": case["name"], "reports": [], "propose": None, "approve": None, "captures": []}
    for r in case.get("reports", []):
        client.report(r["action"], r.get("detail", ""))
        results["reports"].append(r)
    p = case["propose"]
    handle = client.propose(p["mode"], p["payee_id"], p["amount"], p["description"])
    results["propose"] = {"handle": handle, **p}
    assert client.status(handle) == "PENDING"
    results["approve"] = wired.approve_pending()
    assert client.status(handle) == "MINTED"
    for step in case["captures"]:
        expect = step["expect"]
        try:
            out = client.capture(handle, step["payee_id"], step["amount"])
            results["captures"].append({"attempt": step, "result": out})
            if "blocked" in expect:
                raise AssertionError(f"expected block {expect['blocked']}, got {out}")
            for k, v in expect.items():
                assert out.get(k) == v, (out, expect)
        except ServiceError as e:
            results["captures"].append({"attempt": step, "result": {"blocked": e.reason}})
            assert "blocked" in expect, f"unexpected block {e.reason}"
            assert e.reason == expect["blocked"], (e.reason, expect)
    return results


class InjectionHarness(unittest.TestCase):
    def test_all_cases_from_data(self):
        transcripts = []
        for case in CASES:
            with self.subTest(case=case["name"]), WiredService() as wired:
                transcripts.append(run_case(wired, case))
                ledger = wired.ledger()
                self.assertTrue(ledger["chain_ok"])
                kinds = [(e["cls"], e["kind"]) for e in ledger["entries"]]
                self.assertIn(("observed", "captured"), kinds)
                # No reported entry is ever the captured one.
                for e in ledger["entries"]:
                    if e["kind"] == "captured":
                        self.assertEqual(e["cls"], "observed")
                rejected = [e for e in ledger["entries"]
                            if e["kind"] == "capture_rejected"]
                self.assertTrue(rejected, "expected at least one scope rejection")
        # Stash last run for optional external transcript capture.
        InjectionHarness.last_transcripts = transcripts


class SelfDescribingRefusalOverHttp(unittest.TestCase):
    """The bad_mode hint must survive the HTTP trip to the agent: the stable
    code stays in .reason (everything asserts on it) and the valid modes
    arrive in .detail, where the planner can read them."""

    def test_bad_mode_detail_reaches_the_agent(self):
        with WiredService():
            with self.assertRaises(ServiceError) as cm:
                client.propose("confirm", "skyair", "340.00", "United 1234")
            self.assertEqual(cm.exception.reason, "bad_mode")
            self.assertIn("'verify'", cm.exception.detail)
            self.assertIn("'yolo'", cm.exception.detail)


if __name__ == "__main__":
    unittest.main()
