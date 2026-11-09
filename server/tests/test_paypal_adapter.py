"""Offline tests for SandboxPayPal using an injected fake transport (no network, no credentials).
Run from server/:  python3 -m unittest discover -s tests -t .
"""
import json
import unittest
from decimal import Decimal

from tokenservice.paypal import AUTHORIZE, SandboxPayPal, PayPalError, PayPalUnknown

BASE = "https://api-m.sandbox.paypal.com"


def order_json(intent=AUTHORIZE, status="APPROVED", auths=None):
    pu = {"amount": {"currency_code": "USD", "value": "400.00"}, "payee": {"email_address": "m1@example.com"}}
    if auths:
        pu["payments"] = {"authorizations": auths}
    return {"id": "ORD1", "intent": intent, "status": status, "purchase_units": [pu], "links": []}


class Fake:
    def __init__(self, order, capture_status=201):
        self.order, self.capture_status, self.calls = order, capture_status, []

    def __call__(self, method, url, headers, body):
        path = url[len(BASE):]
        self.calls.append((method, path, headers, json.loads(body) if body and path != "/v1/oauth2/token" else body))
        if path == "/v1/oauth2/token":
            return 200, json.dumps({"access_token": "t", "expires_in": 3600}).encode()
        if method == "GET":
            return 200, json.dumps(self.order).encode()
        if path.endswith("/authorize"):
            return 201, json.dumps(order_json(status="COMPLETED", auths=[
                {"id": "AUTH1", "status": "CREATED", "amount": {"currency_code": "USD", "value": "400.00"}}])).encode()
        if "/capture" in path:
            return self.capture_status, json.dumps(
                {"id": "CAP1", "status": "COMPLETED", "amount": {"currency_code": "USD", "value": "340.00"}}).encode()
        return 500, b"{}"

    def posts(self, suffix):
        return [c for c in self.calls if c[0] == "POST" and c[1].endswith(suffix)]


class SandboxAdapterTests(unittest.TestCase):
    def adapter(self, fake):
        return SandboxPayPal("id", "secret", transport=fake)

    def test_refuses_non_sandbox_env(self):
        with self.assertRaises(ValueError):
            SandboxPayPal("id", "secret", env="production")

    def test_ceiling_enforced_before_any_capture_call(self):
        fake = Fake(order_json())
        with self.assertRaises(PayPalError):
            self.adapter(fake).capture(order_id="ORD1", request_id="tok_x", amount=Decimal("400.01"))
        self.assertEqual(fake.posts("/capture"), [])
        self.assertEqual(fake.posts("/authorize"), [])

    def test_authorize_then_final_capture_with_request_ids(self):
        fake = Fake(order_json())
        cap = self.adapter(fake).capture(order_id="ORD1", request_id="tok_x", amount=Decimal("340.00"))
        self.assertEqual((cap.status, cap.amount, cap.payee_account), ("COMPLETED", Decimal("340.00"), "m1@example.com"))
        (_, _, h_auth, _), = fake.posts("/authorize")
        (_, _, h_cap, body), = fake.posts("/capture")
        self.assertEqual(h_auth["PayPal-Request-Id"], "tok_x:auth")
        self.assertEqual(h_cap["PayPal-Request-Id"], "tok_x:cap")
        self.assertIs(body["final_capture"], True)
        self.assertEqual(body["amount"]["value"], "340.00")

    def test_unapproved_order_is_refused(self):
        fake = Fake(order_json(status="CREATED"))
        with self.assertRaises(PayPalError):
            self.adapter(fake).capture(order_id="ORD1", request_id="tok_x", amount=Decimal("10.00"))

    def test_server_error_on_capture_is_unknown_not_failed(self):
        fake = Fake(order_json(auths=[{"id": "AUTH1", "status": "CREATED"}]), capture_status=503)
        with self.assertRaises(PayPalUnknown):
            self.adapter(fake).capture(order_id="ORD1", request_id="tok_x", amount=Decimal("10.00"))

    def test_definite_refusal_is_error_with_paypal_name(self):
        fake = Fake(order_json(auths=[{"id": "AUTH1", "status": "CREATED"}]), capture_status=422)
        with self.assertRaises(PayPalError):
            self.adapter(fake).capture(order_id="ORD1", request_id="tok_x", amount=Decimal("10.00"))


if __name__ == "__main__":
    unittest.main()
