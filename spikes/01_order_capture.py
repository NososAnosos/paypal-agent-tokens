#!/usr/bin/env python3
"""Spike 1: create, buyer-approve, capture an Orders v2 order (CAPTURE intent) in the sandbox.
Needs ONE click mid-run: open the printed URL, log in as DEMO_BUYER_EMAIL, approve. Times out after 10 min."""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from _pp import PP, approval_url, err_name, load_env, say, verdict, wait_approved  # noqa: E402

AMOUNT = "5.00"


def main():
    env = load_env()
    pp = PP(env)
    say(f"Spike 1: CAPTURE order of USD {AMOUNT} to merchant 1 ({env['DEMO_MERCHANT_1_EMAIL']})")
    st, o = pp.create_order("CAPTURE", AMOUNT, env["DEMO_MERCHANT_1_EMAIL"], "s1")
    if st not in (200, 201):
        say(f"create failed: http {st} {err_name(o)}: {str(o.get('message', ''))[:200]}")
        verdict("capture_ok", value="false", stage="create", error=err_name(o))
        return 1
    oid, url = o["id"], approval_url(o)
    say(f"order {oid} status={o.get('status')}")
    say("")
    say("ACTION NEEDED: open this URL, log in as the sandbox BUYER " + env["DEMO_BUYER_EMAIL"] + ", and approve:")
    say("  " + (url or "(no approval link returned!)"))
    say("")
    if not url:
        verdict("capture_ok", value="false", stage="no_approval_link")
        return 1
    if oid not in wait_approved(pp, [oid], timeout=600):
        say("order never reached APPROVED; not capturing")
        verdict("capture_ok", value="false", stage="approval")
        return 1
    say("APPROVED. Capturing...")
    st, c = pp.call("POST", f"/v2/checkout/orders/{oid}/capture", {}, request_id=f"spike-s1-cap-{oid}")
    if st not in (200, 201):
        say(f"capture failed: http {st} {err_name(c)}: {str(c.get('message', ''))[:200]}")
        verdict("capture_ok", value="false", stage="capture", error=err_name(c))
        return 1
    cap = c["purchase_units"][0]["payments"]["captures"][0]
    payee = c["purchase_units"][0].get("payee", {})
    say(f"capture {cap['id']} status={cap['status']} amount={cap['amount']['value']} {cap['amount']['currency_code']}")
    say(f"order status={c.get('status')} payee_echoed={payee.get('email_address') or payee.get('merchant_id', '-')}")
    # Replay with the SAME request id: idempotency check.
    st2, c2 = pp.call("POST", f"/v2/checkout/orders/{oid}/capture", {}, request_id=f"spike-s1-cap-{oid}")
    cap2 = (c2.get("purchase_units") or [{}])[0].get("payments", {}).get("captures", [{}])[0].get("id")
    verdict("replay_same_request_id", http=st2, same_capture_id=str(cap2 == cap["id"]).lower(),
            error=err_name(c2) if st2 >= 400 else "-")
    verdict("capture_ok", value=str(cap["status"] == "COMPLETED").lower(), capture_status=cap["status"])
    return 0


if __name__ == "__main__":
    sys.exit(main())
