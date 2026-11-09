"""In-memory PayPal stand-in. Mimics the behaviours the trust properties lean on:
buyer approval gate, idempotent request ids, one capture per CAPTURE order,
authorization ceiling, and unknown-outcome failures."""
import itertools
import threading
from decimal import Decimal
from typing import Mapping

from .paypal import AUTHORIZE, CAPTURE, Capture, Order, PayPalError, PayPalUnknown

WEBHOOK_SECRET = "mock-signature"  # stands in for PayPal's signed headers


class MockPayPal:
    def __init__(self):
        self._lock = threading.Lock()
        self._ids = itertools.count(1)
        self.orders: dict[str, Order] = {}
        self._by_request: dict[str, object] = {}
        self.capture_calls = 0  # real PayPal-side captures that took effect
        self.fail_next: str | None = None  # "unknown_before" | "unknown_after" | "declined"

    # -- test / demo helpers (not part of the interface) --
    def buyer_approve(self, order_id: str):
        with self._lock:
            o = self.orders[order_id]
            self.orders[order_id] = Order(**{**o.__dict__, "status": "APPROVED"})

    # -- interface --
    def create_order(self, *, request_id, intent, payee_account, amount, currency):
        with self._lock:
            if request_id in self._by_request:
                return self._by_request[request_id]
            o = Order(f"ORD{next(self._ids)}", intent, "CREATED", amount, currency, payee_account)
            self.orders[o.id] = o
            self._by_request[request_id] = o
            return o

    def get_order(self, order_id):
        with self._lock:
            return self.orders[order_id]

    def capture(self, *, order_id, request_id, amount):
        with self._lock:
            if request_id in self._by_request:
                return self._by_request[request_id]
            o = self.orders[order_id]
            fail, self.fail_next = self.fail_next, None
            if fail == "unknown_before":
                raise PayPalUnknown("timeout before PayPal processed")
            if fail == "declined":
                raise PayPalError("INSTRUMENT_DECLINED")
            if o.status != "APPROVED":
                raise PayPalError(f"ORDER_NOT_APPROVED (status={o.status})")
            if o.intent == CAPTURE and amount != o.amount:
                raise PayPalError("capture amount must equal order amount")
            if o.intent == AUTHORIZE and amount > o.amount:
                raise PayPalError("capture exceeds authorization")
            cap = Capture(f"CAP{next(self._ids)}", o.id, amount, o.currency, o.payee_account, "COMPLETED")
            self.capture_calls += 1
            self.orders[o.id] = Order(**{**o.__dict__, "status": "COMPLETED", "captured": amount})
            self._by_request[request_id] = cap
            if fail == "unknown_after":
                raise PayPalUnknown("timeout after PayPal processed")
            return cap

    def verify_webhook(self, headers: Mapping[str, str], raw_body: bytes) -> bool:
        return headers.get("x-mock-signature") == WEBHOOK_SECRET
