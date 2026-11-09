#!/usr/bin/env python3
"""Spike 2: AUTHORIZE for 400.00 against merchant 1, then probe what PayPal allows on capture.
Attempts, each on its OWN fresh authorization (final_capture=true closes an authorization):
  A. capture 340.00  (expected OK)
  B. capture 401.00  (just over the ceiling)
  C. capture 460.00  (15% over; the suspected tolerance edge)
  D. after A, a second capture of 1.00 on the same authorization (expected rejected)
All three orders are created up front so you approve them in ONE sitting (three clicks, same buyer login).
Times out after 10 min. Whatever PayPal does is recorded; the service caps at the ceiling regardless."""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from _pp import PP, approval_url, err_name, load_env, say, verdict, wait_approved  # noqa: E402

CEILING = "400.00"
ATTEMPTS = [("A_340", "340.00"), ("B_401", "401.00"), ("C_460", "460.00")]


def authorize(pp, oid):
    st, a = pp.call("POST", f"/v2/checkout/orders/{oid}/authorize", {}, request_id=f"spike-s2-auth-{oid}")
    if st not in (200, 201):
        return None, f"http {st} {err_name(a)}: {str(a.get('message', ''))[:150]}"
    au = a["purchase_units"][0]["payments"]["authorizations"][0]
    return au, None


def capture(pp, auth_id, value, tag):
    return pp.call("POST", f"/v2/payments/authorizations/{auth_id}/capture",
                   {"amount": {"currency_code": "USD", "value": value}, "final_capture": True},
                   request_id=f"spike-s2-{tag}-{auth_id}")


def main():
    env = load_env()
    pp = PP(env)
    m1 = env["DEMO_MERCHANT_1_EMAIL"]
    say(f"Spike 2: three AUTHORIZE orders of USD {CEILING} to merchant 1 ({m1})")
    orders = {}
    for tag, _ in ATTEMPTS:
        st, o = pp.create_order("AUTHORIZE", CEILING, m1, "s2" + tag)
        if st not in (200, 201):
            say(f"create failed for {tag}: http {st} {err_name(o)}")
            verdict("authorize_create", attempt=tag, value="false", error=err_name(o))
            return 1
        orders[tag] = (o["id"], approval_url(o))
    say("")
    say("ACTION NEEDED: approve ALL THREE of these as sandbox BUYER " + env["DEMO_BUYER_EMAIL"] + " (any order):")
    for tag, (oid, url) in orders.items():
        say(f"  {tag}: {url or '(no approval link!)'}")
    say("")
    approved = wait_approved(pp, [oid for oid, _ in orders.values()], timeout=600)
    rc = 0
    first_auth = None
    for tag, value in ATTEMPTS:
        oid = orders[tag][0]
        if oid not in approved:
            say(f"{tag}: order {oid} was never approved; skipping")
            verdict("attempt", attempt=tag, requested=value, result="skipped_not_approved")
            rc = 1
            continue
        au, err = authorize(pp, oid)
        if not au:
            say(f"{tag}: authorize failed: {err}")
            verdict("attempt", attempt=tag, requested=value, result="authorize_failed")
            rc = 1
            continue
        say(f"{tag}: authorization {au['id']} status={au['status']} amount={au['amount']['value']}")
        st, c = capture(pp, au["id"], value, "cap")
        if st in (200, 201):
            verdict("attempt", attempt=tag, requested=value, ceiling=CEILING, result="ALLOWED",
                    capture_status=c.get("status"), captured=c.get("amount", {}).get("value"))
            if tag == "A_340":
                verdict("capture_340_ok", value=str(c.get("status") == "COMPLETED").lower())
                first_auth = au["id"]
        else:
            verdict("attempt", attempt=tag, requested=value, ceiling=CEILING, result="REJECTED",
                    http=st, error=err_name(c))
            say(f"   message: {str(c.get('message', ''))[:200]}")
            if tag == "A_340":
                verdict("capture_340_ok", value="false", error=err_name(c))
    if first_auth:
        st, c = capture(pp, first_auth, "1.00", "recap")
        verdict("attempt", attempt="D_recapture_after_final", requested="1.00",
                result="ALLOWED" if st in (200, 201) else "REJECTED", http=st,
                error=err_name(c) if st >= 400 else "-")
    say("Note: our adapter refuses amount > order ceiling before calling PayPal, so B and C show what PayPal "
        "itself would do, not what the service would permit.")
    return rc


if __name__ == "__main__":
    sys.exit(main())
