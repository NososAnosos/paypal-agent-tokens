#!/usr/bin/env python3
"""Spike 3: may the app create an order whose payee is NOT its own account? No buyer click needed.
Probes: merchant 2 (the real question), merchant 1 (control), and a nonexistent email (does PayPal validate payees at all?).
Orders are created but never approved or captured."""
import os
import sys
import uuid

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from _pp import PP, err_name, load_env, say, verdict  # noqa: E402


def probe(pp, label, email):
    st, o = pp.create_order("CAPTURE", "1.00", email, "s3" + label)
    if st in (200, 201):
        st2, d = pp.call("GET", f"/v2/checkout/orders/{o['id']}")
        payee = (d.get("purchase_units") or [{}])[0].get("payee", {}) if st2 == 200 else {}
        verdict("payee", target=label, result="permitted", order=o["id"], status=o.get("status"),
                payee_email_echoed=payee.get("email_address", "-"), payee_merchant_id_echoed=payee.get("merchant_id", "-"))
    else:
        verdict("payee", target=label, result="rejected", http=st, error=err_name(o))
        say(f"   message: {str(o.get('message', ''))[:200]}")
    return st in (200, 201)


def main():
    env = load_env()
    pp = PP(env)
    say("Spike 3: payee probes (CAPTURE, USD 1.00, never approved or captured)")
    probe(pp, "merchant_1_control", env["DEMO_MERCHANT_1_EMAIL"])
    ok = probe(pp, "merchant_2", env["DEMO_MERCHANT_2_EMAIL"])
    probe(pp, "nonexistent_email", f"no-such-{uuid.uuid4().hex[:8]}@example.com")
    verdict("merchant_2_payee", value="permitted" if ok else "rejected")
    return 0


if __name__ == "__main__":
    sys.exit(main())
