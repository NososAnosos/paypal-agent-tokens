#!/usr/bin/env python3
"""Print offline Verify + beat-4 injection transcripts for PAYPAL-WIRING-SUMMARY.md."""
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "server"))
sys.path.insert(0, str(ROOT / "agent"))
sys.path.insert(0, str(ROOT / "tests"))

from cases import BEAT4_YOLO_TV  # noqa: E402
from harness import WiredService  # noqa: E402
from shopper import client  # noqa: E402
from shopper.client import ServiceError  # noqa: E402


def run_case(wired, case):
    results = {"name": case["name"], "reports": [], "propose": None, "approve": None, "captures": []}
    for r in case.get("reports", []):
        client.report(r["action"], r.get("detail", ""))
        results["reports"].append(r)
    p = case["propose"]
    handle = client.propose(p["mode"], p["payee_id"], p["amount"], p["description"])
    results["propose"] = {"handle": handle, **p}
    results["approve"] = wired.approve_pending()
    for step in case["captures"]:
        try:
            out = client.capture(handle, step["payee_id"], step["amount"])
            results["captures"].append({"attempt": step, "result": out})
        except ServiceError as e:
            results["captures"].append({"attempt": step, "result": {"blocked": e.reason}})
    return results


def main():
    print("=== OFFLINE VERIFY LOOP ===")
    with WiredService() as wired:
        client.report("search_flights", "SFO-JFK")
        client.report("read_reviews", "UA1234")
        handle = client.propose("verify", "skyair", "340.00", "United 1234")
        print(f"status_after_propose={client.status(handle)}")
        approved = wired.approve_pending()
        print(f"approve={json.dumps({k: approved[k] for k in ('order_id','status','approval_url','payee_id','amount','currency')}, sort_keys=True)}")
        print(f"status_after_approve={client.status(handle)}")
        cap = client.capture(handle, "skyair", "340.00")
        print(f"capture={json.dumps(cap, sort_keys=True)}")
        ledger = wired.ledger()
        print(f"chain_ok={ledger['chain_ok']}")
        for e in ledger["entries"]:
            print(f"  ledger[{e['seq']}] cls={e['cls']} kind={e['kind']} actor={e['actor']} data={json.dumps(e['data'], sort_keys=True)}")

    print()
    print("=== OFFLINE BEAT4 INJECTION (YOLO) ===")
    with WiredService() as wired:
        t = run_case(wired, BEAT4_YOLO_TV)
        print(f"case={t['name']}")
        for r in t["reports"]:
            print(f"  report action={r['action']} detail={r.get('detail','')}")
        print(f"  propose mode={t['propose']['mode']} payee={t['propose']['payee_id']} amount={t['propose']['amount']}")
        print(f"  approve order_id={t['approve'].get('order_id')} status={t['approve'].get('status')}")
        for c in t["captures"]:
            print(f"  capture payee={c['attempt']['payee_id']} amount={c['attempt']['amount']} -> {json.dumps(c['result'], sort_keys=True)}")
        ledger = wired.ledger()
        print(f"chain_ok={ledger['chain_ok']}")
        for e in ledger["entries"]:
            print(f"  ledger[{e['seq']}] cls={e['cls']} kind={e['kind']} data={json.dumps(e['data'], sort_keys=True)}")


if __name__ == "__main__":
    main()
