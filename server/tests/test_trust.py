"""Trust-property tests. Each test pins one claim from docs/REVIEW.md; nothing else is tested here.
Run from server/:  python3 -m unittest discover -s tests -t .
"""
import json
import re
import sqlite3
import threading
import unittest
from decimal import Decimal
from pathlib import Path

from tokenservice.mock_paypal import MockPayPal
from tokenservice.service import (Config, Forbidden, Principal, Rejected, TokenService, VERIFY, YOLO)

AGENT, OTHER_AGENT = Principal("agent", "a1"), Principal("agent", "a2")
HUMAN, SYSTEM = Principal("human", "h1"), Principal("system", "reconciler")


class Base(unittest.TestCase):
    def setUp(self):
        self.t = [1000.0]
        self.pp = MockPayPal()
        self.svc = TokenService(self.pp, clock=lambda: self.t[0])

    def minted(self, mode=VERIFY, amount="340.00", payee="skyair", buyer_approves=True, agent=AGENT):
        h = self.svc.propose(agent, mode=mode, payee_id=payee, amount=amount, description="United 1234")
        order = self.svc.approve(HUMAN, h)
        if buyer_approves:
            self.pp.buyer_approve(order)
        return h

    def reason(self, fn, *a, **k):
        with self.assertRaises(Rejected) as cm:
            fn(*a, **k)
        return cm.exception.reason

    def buy(self, h, payee="skyair", amount="340.00", agent=AGENT):
        return self.svc.capture(agent, h, payee_id=payee, amount=amount)


class SingleUse(Base):
    def test_second_capture_rejected_and_paypal_hit_once(self):
        h = self.minted()
        self.assertEqual(self.buy(h)["state"], "CAPTURED")
        self.assertEqual(self.reason(self.buy, h), "token_already_used")
        self.assertEqual(self.pp.capture_calls, 1)

    def test_concurrent_captures_exactly_one_wins(self):
        h = self.minted()
        results = []

        def go():
            try:
                self.buy(h)
                results.append("ok")
            except Rejected as e:
                results.append(e.reason)
        ts = [threading.Thread(target=go) for _ in range(12)]
        [x.start() for x in ts]
        [x.join() for x in ts]
        self.assertEqual(results.count("ok"), 1)
        self.assertEqual(self.pp.capture_calls, 1)

    def test_double_approve_mints_one_token(self):
        h = self.svc.propose(AGENT, mode=VERIFY, payee_id="skyair", amount="10.00")
        self.svc.approve(HUMAN, h)
        self.assertEqual(self.reason(self.svc.approve, HUMAN, h), "not_pending")

    def test_declined_capture_burns_token_and_unknown_never_reopens(self):
        h = self.minted()
        self.pp.fail_next = "unknown_after"
        self.assertEqual(self.reason(self.buy, h), "outcome_unknown")
        self.assertEqual(self.reason(self.buy, h), "token_already_used")  # not retryable
        tid = self.svc._q("SELECT id FROM tokens").fetchone()[0]
        self.assertEqual(self.svc.reconcile(SYSTEM, tid), "CAPTURED")  # PayPal says it did happen
        self.assertEqual(self.pp.capture_calls, 1)


class ScopeEnforcement(Base):
    def test_verify_requires_exact_amount_and_payee(self):
        h = self.minted()
        self.assertEqual(self.reason(self.buy, h, amount="340.01"), "amount_not_exact")
        self.assertEqual(self.reason(self.buy, h, amount="339.99"), "amount_not_exact")
        self.assertEqual(self.reason(self.buy, h, payee="megamart"), "payee_out_of_scope")
        self.assertEqual(self.pp.capture_calls, 0)
        self.assertEqual(self.buy(h)["state"], "CAPTURED")  # rejected probes did not burn the token

    def test_yolo_ceiling_holds_and_allows_less(self):
        h = self.minted(mode=YOLO, amount="400.00")
        self.assertEqual(self.reason(self.buy, h, amount="900.00"), "amount_over_ceiling")
        self.assertEqual(self.reason(self.buy, h, amount="400.01"), "amount_over_ceiling")
        self.assertEqual(self.buy(h, amount="340.00")["amount"], "340.00")

    def test_agent_cannot_name_unknown_payee_or_float_amount(self):
        self.assertEqual(self.reason(self.svc.propose, AGENT, mode=VERIFY, payee_id="evil", amount="1.00"),
                         "unknown_payee")
        with self.assertRaises(ValueError):
            self.svc.propose(AGENT, mode=VERIFY, payee_id="skyair", amount=340.0)

    def test_expiry_and_ttl_starts_at_approval(self):
        h = self.svc.propose(AGENT, mode=VERIFY, payee_id="skyair", amount="340.00")
        self.t[0] += 250  # human is slow but inside proposal ttl
        order = self.svc.approve(HUMAN, h)
        self.pp.buyer_approve(order)
        self.t[0] += 599  # inside token ttl measured from approval
        self.assertEqual(self.buy(h)["state"], "CAPTURED")
        h2 = self.minted()
        self.t[0] += 601
        self.assertEqual(self.reason(self.buy, h2), "token_expired")

    def test_unanswered_proposal_expires_and_cannot_be_approved(self):
        h = self.svc.propose(AGENT, mode=VERIFY, payee_id="skyair", amount="5.00")
        self.t[0] += 301
        self.assertEqual(self.svc.status(AGENT, h), "EXPIRED")
        self.assertEqual(self.reason(self.svc.approve, HUMAN, h), "not_pending")

    def test_no_capture_without_buyer_approval_at_paypal(self):
        h = self.minted(buyer_approves=False)
        self.assertEqual(self.reason(self.buy, h), "order_not_approved_or_mismatched")

    def test_other_agent_cannot_use_handle(self):
        h = self.minted()
        self.assertEqual(self.reason(self.buy, h, agent=OTHER_AGENT), "no_token_for_handle")

    def test_proposal_flood_is_capped(self):
        for _ in range(3):
            self.svc.propose(AGENT, mode=VERIFY, payee_id="skyair", amount="1.00")
        self.assertEqual(self.reason(self.svc.propose, AGENT, mode=VERIFY, payee_id="skyair", amount="1.00"),
                         "proposal_rate_limit")


class Principals(Base):
    def test_agent_cannot_approve_decline_or_read_pending(self):
        h = self.svc.propose(AGENT, mode=VERIFY, payee_id="skyair", amount="5.00")
        for fn in (self.svc.approve, self.svc.decline, self.svc.pending):
            with self.assertRaises(Forbidden):
                fn(AGENT, *([h] if fn != self.svc.pending else []))
        with self.assertRaises(Forbidden):
            self.svc.capture(HUMAN, h, payee_id="skyair", amount="5.00")

    def test_agent_code_has_no_route_to_paypal_or_approval(self):
        root = Path(__file__).resolve().parents[2] / "agent"
        src = "\n".join(p.read_text() for p in root.rglob("*.py"))
        self.assertNotRegex(src, r"tokenservice|paypal|/human/")  # only the agent HTTP surface may be used


class LedgerAndWebhooks(Base):
    def test_ledger_rejects_update_delete_and_detects_tamper(self):
        self.minted()
        with self.assertRaises(sqlite3.DatabaseError):
            self.svc._q("UPDATE ledger SET kind='x'")
        with self.assertRaises(sqlite3.DatabaseError):
            self.svc._q("DELETE FROM ledger")
        self.assertTrue(self.svc.ledger.verify())
        self.svc._q("DROP TRIGGER ledger_no_update")  # attacker with raw DB access
        self.svc._q("UPDATE ledger SET data='{}' WHERE seq=1")
        self.assertFalse(self.svc.ledger.verify())

    def test_agent_reports_are_class_reported_never_observed(self):
        self.svc.report(AGENT, "search_flights", "SFO-JFK")
        e = self.svc.ledger.entries()[-1]
        self.assertEqual((e["cls"], e["kind"]), ("reported", "free_action"))

    def test_unsigned_webhook_is_ignored_and_cannot_fake_a_capture(self):
        body = json.dumps({"id": "WH1", "event_type": "PAYMENT.CAPTURE.COMPLETED", "resource": {"id": "CAPX"}}).encode()
        self.assertFalse(self.svc.handle_webhook({}, body))
        self.assertTrue(self.svc.handle_webhook({"X-Mock-Signature": "mock-signature"}, body))
        self.assertTrue(self.svc.handle_webhook({"X-Mock-Signature": "mock-signature"}, body))  # duplicate: no-op
        kinds = [e["kind"] for e in self.svc.ledger.entries()]
        self.assertNotIn("captured", kinds)
        self.assertEqual(kinds.count("webhook"), 1)


class SelfDescribingRefusals(Base):
    def test_bad_mode_names_the_valid_modes(self):
        with self.assertRaises(Rejected) as cm:
            self.svc.propose(AGENT, mode="confirm", payee_id="skyair", amount="340.00")
        self.assertEqual(cm.exception.reason, "bad_mode")  # stable machine code unchanged
        self.assertIn("'verify'", str(cm.exception))  # ...but the message teaches the fix
        self.assertIn("'yolo'", str(cm.exception))


if __name__ == "__main__":
    unittest.main()
