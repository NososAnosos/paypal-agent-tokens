"""PayPal adapter INTERFACE. The service depends only on this.

Implementations: mock_paypal.MockPayPal (tests) and SandboxPayPal (below; sandbox
only, no live endpoint exists in this codebase). See docs/REVIEW.md "Week-1 spikes".
"""
import base64
import json
import os
import threading
import time
import urllib.error
import urllib.request
from dataclasses import dataclass
from decimal import Decimal
from typing import Mapping, Protocol

CAPTURE, AUTHORIZE = "CAPTURE", "AUTHORIZE"  # Orders v2 `intent`


class PayPalError(Exception):
    """Definite failure: PayPal answered and refused. Safe to treat the attempt as failed."""


class PayPalUnknown(Exception):
    """Timeout / 5xx / connection loss: the outcome is UNKNOWN. Must reconcile, never retry blindly."""


@dataclass(frozen=True)
class Order:
    id: str
    intent: str
    status: str  # CREATED | APPROVED | COMPLETED | VOIDED  (PayPal also has others)
    amount: Decimal
    currency: str
    payee_account: str  # sandbox business account (email or merchant id)
    captured: Decimal = Decimal("0")  # total captured so far
    approval_url: str = ""  # where the buyer approves (sandbox adapter only)


@dataclass(frozen=True)
class Capture:
    id: str
    order_id: str
    amount: Decimal
    currency: str
    payee_account: str
    status: str  # COMPLETED | DECLINED | PENDING


class PayPalAdapter(Protocol):
    def create_order(self, *, request_id: str, intent: str, payee_account: str,
                     amount: Decimal, currency: str) -> Order:
        """POST /v2/checkout/orders with PayPal-Request-Id=request_id (idempotent).
        Exactly one purchase_unit. TODO: spike whether payee may differ from the app's account (REVIEW P1-1)."""

    def get_order(self, order_id: str) -> Order:
        """GET /v2/checkout/orders/{id}. Status APPROVED means the human approved at PayPal (REVIEW P1-2)."""

    def capture(self, *, order_id: str, request_id: str, amount: Decimal) -> Capture:
        """CAPTURE intent: POST /v2/checkout/orders/{id}/capture.
        AUTHORIZE intent: authorize then POST /v2/payments/authorizations/{id}/capture with
        amount and final_capture=true (REVIEW P0-2a). Idempotent on request_id.
        Raises PayPalError (definite) or PayPalUnknown (outcome unknown)."""

    def verify_webhook(self, headers: Mapping[str, str], raw_body: bytes) -> bool:
        """POST /v1/notifications/verify-webhook-signature with PAYPAL_WEBHOOK_ID and the RAW body."""


# ---------------------------------------------------------------------------
# Real sandbox adapter. The host is a constant and PAYPAL_ENV must say
# "sandbox"; there is no code path to any other endpoint.
# ---------------------------------------------------------------------------
SANDBOX_BASE = "https://api-m.sandbox.paypal.com"


def load_dotenv(path) -> dict:
    """Minimal .env reader (stdlib only). Fails loudly if the file is missing. Never prints values."""
    if not os.path.isfile(path):
        raise SystemExit(f"missing {path}: copy .env.example to .env and fill it in")
    out = {}
    with open(path, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line and not line.startswith("#") and "=" in line:
                k, v = line.split("=", 1)
                out[k.strip()] = v.strip().strip('"').strip("'")
    return out


def _money(d: Decimal) -> str:
    return f"{d:.2f}"


class SandboxPayPal:
    """PayPalAdapter against the PayPal sandbox (Orders v2 + Payments v2).

    `transport(method, url, headers, body) -> (status, bytes)` is injectable for tests.
    PayPalError: PayPal definitely refused (or nothing mutating was sent).
    PayPalUnknown: outcome of a mutating call cannot be known (timeout, connection loss, 5xx, 429).
    """

    def __init__(self, client_id: str, client_secret: str, env: str = "sandbox", webhook_id: str = "",
                 transport=None, timeout: float = 30.0,
                 return_url: str = "https://example.com/return", cancel_url: str = "https://example.com/cancel"):
        if env != "sandbox":
            raise ValueError("PAYPAL_ENV must be 'sandbox'; this codebase has no other endpoint")
        if not client_id or not client_secret:
            raise ValueError("PAYPAL_CLIENT_ID / PAYPAL_CLIENT_SECRET required")
        self._basic = base64.b64encode(f"{client_id}:{client_secret}".encode()).decode()  # never logged
        self.webhook_id, self.timeout = webhook_id, timeout
        self.return_url, self.cancel_url = return_url, cancel_url
        self._transport = transport or self._urllib_transport
        self._tok, self._tok_exp, self._lock = None, 0.0, threading.Lock()

    @classmethod
    def from_env(cls, path=".env", **kw):
        e = load_dotenv(path)
        return cls(e.get("PAYPAL_CLIENT_ID", ""), e.get("PAYPAL_CLIENT_SECRET", ""),
                   e.get("PAYPAL_ENV", "sandbox"), e.get("PAYPAL_WEBHOOK_ID", ""), **kw)

    # -- plumbing --
    def _urllib_transport(self, method, url, headers, body):
        req = urllib.request.Request(url, data=body, headers=headers, method=method)
        try:
            with urllib.request.urlopen(req, timeout=self.timeout) as r:
                return r.status, r.read()
        except urllib.error.HTTPError as e:
            return e.code, e.read()

    def _access_token(self) -> str:
        with self._lock:
            if self._tok and time.time() < self._tok_exp - 60:
                return self._tok
            try:
                st, raw = self._transport("POST", SANDBOX_BASE + "/v1/oauth2/token",
                                          {"Authorization": "Basic " + self._basic,
                                           "Content-Type": "application/x-www-form-urlencoded"},
                                          b"grant_type=client_credentials")
            except Exception as e:  # nothing mutating has been sent yet: definite failure
                raise PayPalError(f"oauth_unreachable: {type(e).__name__}") from None
            if st != 200:
                raise PayPalError(f"oauth_failed: http {st}")
            d = json.loads(raw)
            self._tok, self._tok_exp = d["access_token"], time.time() + int(d.get("expires_in", 300))
            return self._tok

    def _call(self, method, path, body=None, request_id=None, raw_body=None):
        headers = {"Authorization": "Bearer " + self._access_token(), "Content-Type": "application/json",
                   "Prefer": "return=representation"}
        if request_id:
            headers["PayPal-Request-Id"] = request_id[:108]
        data = raw_body if raw_body is not None else (None if body is None else json.dumps(body).encode())
        try:
            st, raw = self._transport(method, SANDBOX_BASE + path, headers, data)
        except Exception as e:
            if method == "GET":
                raise PayPalError(f"unreachable: {type(e).__name__}") from None
            raise PayPalUnknown(f"transport: {type(e).__name__}") from None
        try:
            d = json.loads(raw) if raw else {}
        except ValueError:
            d = {}
        if st >= 500 or st == 429:
            if method == "GET":
                raise PayPalError(f"http {st}")
            raise PayPalUnknown(f"http {st}")
        if st >= 400:
            issues = ",".join(x.get("issue", "") for x in d.get("details", []) if isinstance(x, dict))
            raise PayPalError(f"{d.get('name', 'HTTP_' + str(st))}{'/' + issues if issues else ''}: "
                              f"{str(d.get('message', ''))[:200]} (debug_id={d.get('debug_id', '-')})")
        return d

    @staticmethod
    def _order(d: dict) -> Order:
        pu = d["purchase_units"][0]
        payee = pu.get("payee", {})
        caps = pu.get("payments", {}).get("captures", [])
        captured = sum((Decimal(c["amount"]["value"]) for c in caps if c.get("status") in ("COMPLETED", "PENDING")),
                       Decimal("0"))
        link = next((x["href"] for x in d.get("links", []) if x.get("rel") in ("payer-action", "approve")), "")
        return Order(d["id"], d["intent"], d["status"], Decimal(pu["amount"]["value"]),
                     pu["amount"]["currency_code"], payee.get("email_address") or payee.get("merchant_id", ""),
                     captured, link)

    # -- interface --
    def create_order(self, *, request_id, intent, payee_account, amount, currency):
        if intent not in (CAPTURE, AUTHORIZE):
            raise PayPalError("bad_intent")
        payee = {"email_address": payee_account} if "@" in payee_account else {"merchant_id": payee_account}
        d = self._call("POST", "/v2/checkout/orders", request_id=request_id, body={
            "intent": intent,
            "purchase_units": [{"amount": {"currency_code": currency, "value": _money(amount)}, "payee": payee}],
            "payment_source": {"paypal": {"experience_context": {
                "user_action": "PAY_NOW", "return_url": self.return_url, "cancel_url": self.cancel_url}}}})
        return self._order(d)

    def get_order(self, order_id):
        return self._order(self._call("GET", f"/v2/checkout/orders/{order_id}"))

    def capture(self, *, order_id, request_id, amount):
        raw_order = self._call("GET", f"/v2/checkout/orders/{order_id}")
        order = self._order(raw_order)
        if order.status not in ("APPROVED", "COMPLETED"):  # COMPLETED: resuming after a crash; request ids dedupe
            raise PayPalError(f"ORDER_NOT_APPROVED (status={order.status})")
        if order.intent == CAPTURE:
            if amount != order.amount:  # PayPal would refuse too; fail before spending a call
                raise PayPalError("capture amount must equal order amount")
            d = self._call("POST", f"/v2/checkout/orders/{order_id}/capture", body={}, request_id=request_id)
            c = d["purchase_units"][0]["payments"]["captures"][0]
            return Capture(c["id"], order_id, Decimal(c["amount"]["value"]), c["amount"]["currency_code"],
                           order.payee_account, c["status"])
        # AUTHORIZE: the ceiling is enforced HERE, whatever over-capture tolerance PayPal has.
        if amount > order.amount:
            raise PayPalError("capture exceeds authorization ceiling")
        auths = raw_order["purchase_units"][0].get("payments", {}).get("authorizations", [])
        if not auths:
            raw_order = self._call("POST", f"/v2/checkout/orders/{order_id}/authorize", body={},
                                   request_id=request_id + ":auth")
            auths = raw_order["purchase_units"][0]["payments"]["authorizations"]
        if auths[0].get("status") not in ("CREATED", "PENDING", "CAPTURED", "PARTIALLY_CAPTURED"):
            raise PayPalError(f"authorization unusable (status={auths[0].get('status')})")
        d = self._call("POST", f"/v2/payments/authorizations/{auths[0]['id']}/capture",
                       request_id=request_id + ":cap",
                       body={"amount": {"currency_code": order.currency, "value": _money(amount)},
                             "final_capture": True})
        return Capture(d["id"], order_id, Decimal(d["amount"]["value"]), d["amount"]["currency_code"],
                       order.payee_account, d["status"])

    def verify_webhook(self, headers, raw_body):
        """The RAW body is spliced in byte-for-byte; re-serialising parsed JSON can break the signature."""
        h = {k.lower(): v for k, v in headers.items()}
        keys = ("auth_algo", "cert_url", "transmission_id", "transmission_sig", "transmission_time")
        if not self.webhook_id or any("paypal-" + k.replace("_", "-") not in h for k in keys):
            return False
        fields = {k: h["paypal-" + k.replace("_", "-")] for k in keys}
        fields["webhook_id"] = self.webhook_id
        body = json.dumps(fields).encode()[:-1] + b', "webhook_event": ' + raw_body + b"}"
        try:
            d = self._call("POST", "/v1/notifications/verify-webhook-signature", raw_body=body)
        except (PayPalError, PayPalUnknown):
            return False
        return d.get("verification_status") == "SUCCESS"
