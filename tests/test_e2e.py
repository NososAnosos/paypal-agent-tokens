"""Offline end-to-end: agent HTTP → mock TokenService → ledger.

Run from repo root:
  python3 -m unittest discover -s tests -t .
"""
import threading
import unittest

from .harness import WiredService  # noqa: F401 — sets sys.path for shopper/tokenservice
from .cases import BEAT4_YOLO_TV
from .test_injection import run_case
from shopper import client
from shopper.loop import ScriptedPlanner, run


class OfflineE2E(unittest.TestCase):
    def test_verify_loop_report_propose_approve_capture(self):
        with WiredService() as wired:
            client.report("search_flights", "SFO-JFK")
            client.report("read_reviews", "UA1234")
            handle = client.propose("verify", "skyair", "340.00", "United 1234")
            self.assertEqual(client.status(handle), "PENDING")
            approved = wired.approve_pending()
            self.assertTrue(approved.get("order_id"))
            # Mock mode: approval_url is empty string (correct).
            self.assertEqual(approved.get("approval_url", ""), "")
            self.assertEqual(client.status(handle), "MINTED")
            cap = client.capture(handle, "skyair", "340.00")
            self.assertEqual(cap["state"], "CAPTURED")

            ledger = wired.ledger()
            self.assertTrue(ledger["chain_ok"])
            reported = [e for e in ledger["entries"] if e["cls"] == "reported"]
            self.assertGreaterEqual(len(reported), 2)
            for e in reported:
                self.assertEqual(e["kind"], "free_action")
            captured = [e for e in ledger["entries"]
                        if e["cls"] == "observed" and e["kind"] == "captured"]
            self.assertEqual(len(captured), 1)
            # No reported entry is ever the captured one.
            for e in ledger["entries"]:
                if e["kind"] == "captured":
                    self.assertEqual(e["cls"], "observed")
            OfflineE2E.verify_transcript = {
                "handle": handle,
                "approve": approved,
                "capture": cap,
                "ledger": ledger,
            }

    def test_yolo_scripted_planner_injection(self):
        """Full YOLO loop with ScriptedPlanner (overlaps W5 canonical case)."""
        with WiredService() as wired:
            stop = threading.Event()
            t = threading.Thread(target=wired.auto_approve_until, args=(stop,), daemon=True)
            t.start()
            try:
                planner = ScriptedPlanner(mode="yolo")
                # Speed up wait_for_approval polling for the offline suite.
                for a in planner.steps:
                    if a.tool == "wait_for_approval":
                        a.args["interval"] = 0.05
                        a.args["polls"] = 100
                history = run(planner, max_steps=20)
            finally:
                stop.set()
                t.join(timeout=2)

            results = [h["result"] for h in history]
            # Injected TV buy blocked; in-scope flight captured.
            blocked = [r for r in results if r.get("blocked") == "payee_out_of_scope"]
            captured = [r for r in results if r.get("state") == "CAPTURED"]
            self.assertTrue(blocked, results)
            self.assertTrue(captured, results)

            ledger = wired.ledger()
            self.assertTrue(ledger["chain_ok"])
            OfflineE2E.yolo_scripted_transcript = {"history": [
                {"tool": h["action"].tool, "args": h["action"].args, "result": h["result"]}
                for h in history
            ], "ledger": ledger}

    def test_canonical_injection_case_via_shared_runner(self):
        """W4/W5 reuse: same run_case implementation as the data harness."""
        with WiredService() as wired:
            transcript = run_case(wired, BEAT4_YOLO_TV)
            self.assertEqual(transcript["captures"][0]["result"]["blocked"], "payee_out_of_scope")
            self.assertEqual(transcript["captures"][1]["result"]["state"], "CAPTURED")
            OfflineE2E.beat4_transcript = transcript


if __name__ == "__main__":
    unittest.main()
