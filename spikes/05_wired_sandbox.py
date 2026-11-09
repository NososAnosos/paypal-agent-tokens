#!/usr/bin/env python3
"""Spike 5: wired sandbox smoke — propose → mint → stop at buyer approval (NO clicks).

Builds TokenService in-process with SandboxPayPal + G2 registry from ../.env.
Asserts approval_url is present, then that a pre-approval capture is refused
without burning the token. Creates real sandbox orders that simply lapse.
"""
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "server"))

from tokenservice.paypal import SandboxPayPal, load_dotenv  # noqa: E402
from tokenservice.service import Principal, Rejected, TokenService, VERIFY  # noqa: E402

AGENT, HUMAN = Principal("agent", "spike5-agent"), Principal("human", "spike5-human")


def say(msg):
    print(msg, flush=True)


def verdict(name, **kv):
    say("VERDICT " + name + " " + " ".join(f"{k}={v}" for k, v in kv.items()))


def main():
    env_path = os.environ.get("ENV_FILE", os.path.join(ROOT, ".env"))
    e = load_dotenv(env_path)
    for k in ("DEMO_MERCHANT_1_EMAIL", "DEMO_MERCHANT_2_EMAIL"):
        if not e.get(k):
            sys.exit(f"FATAL: .env missing {k}")
    payees = {"skyair": e["DEMO_MERCHANT_1_EMAIL"], "megamart": e["DEMO_MERCHANT_2_EMAIL"]}
    svc = TokenService(SandboxPayPal.from_env(env_path), payees=payees)

    say("Spike 5: wired sandbox smoke (verify skyair 340.00; NO buyer click)")
    handle = svc.propose(AGENT, mode=VERIFY, payee_id="skyair", amount="340.00",
                         description="United 1234 (spike5; will lapse)")
    say(f"  proposed handle={handle}")

    order_id = svc.approve(HUMAN, handle)
    info = svc.order_status(HUMAN, handle)
    status = info["status"]
    url = info["approval_url"]
    say(f"  minted order_id={info['order_id']} status={status}")
    # Never print secrets; order id + status + url host only.
    if url:
        # Show scheme+host only — full redirect URLs can embed tokens in query strings.
        from urllib.parse import urlsplit
        parts = urlsplit(url)
        say(f"  approval_url_host={parts.scheme}://{parts.netloc} (path omitted)")
    else:
        say("  approval_url=(empty)")

    ok_order = bool(order_id) and info["order_id"] == order_id
    ok_url = bool(url)
    ok_status = status in ("CREATED", "PAYER_ACTION_REQUIRED")
    verdict("order_created", value="ok" if ok_order else "fail", order=info["order_id"])
    verdict("approval_url_present", value="ok" if ok_url else "fail")
    verdict("order_status_pre_buyer", value="ok" if ok_status else "fail", status=status)

    # Capture BEFORE any buyer approval: service gate must refuse and burn nothing.
    try:
        svc.capture(AGENT, handle, payee_id="skyair", amount="340.00")
        verdict("pre_approval_capture_refused", value="fail", reason="capture_succeeded")
        burned = True
    except Rejected as ex:
        ok_reason = ex.reason == "order_not_approved_or_mismatched"
        verdict("pre_approval_capture_refused",
                value="ok" if ok_reason else "fail", reason=ex.reason)
        state = svc.status(AGENT, handle)
        still_minted = state == "MINTED"
        verdict("token_still_minted", value="ok" if still_minted else "fail", state=state)
        burned = not still_minted

    all_ok = ok_order and ok_url and ok_status and not burned
    verdict("wired_sandbox_smoke", value="ok" if all_ok else "fail")
    return 0 if all_ok else 1


if __name__ == "__main__":
    sys.exit(main())
