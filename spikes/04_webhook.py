#!/usr/bin/env python3
"""Spike 4: real webhook delivery, signature verification, latency, and re-GET of the order.

usage:  python3 spikes/04_webhook.py https://<your-tunnel-host>/webhooks/paypal [local_port=8803]

Run order: 1) start your tunnel forwarding the public URL to localhost:<local_port>
           2) run THIS script (it registers the URL as a sandbox webhook if none matches, then listens)
           3) in another terminal run spikes/01 or 02 so REAL events fire (CHECKOUT.ORDER.APPROVED,
              PAYMENT.CAPTURE.COMPLETED, PAYMENT.AUTHORIZATION.CREATED)
Ctrl-C, or the 20 min timeout, ends the run. Dashboard 'simulated' events are expected to FAIL verification.
The payload is never trusted: every event is re-fetched from PayPal and the order is re-GET."""
import json
import os
import queue
import sys
import threading
import time
from datetime import datetime, timezone
from http.server import BaseHTTPRequestHandler, HTTPServer

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from _pp import PP, err_name, load_env, say, verdict  # noqa: E402

EVENTS = ["CHECKOUT.ORDER.APPROVED", "PAYMENT.CAPTURE.COMPLETED", "PAYMENT.AUTHORIZATION.CREATED"]
TIMEOUT = 20 * 60
inbox = queue.Queue()


class Handler(BaseHTTPRequestHandler):
    def do_POST(self):
        raw = self.rfile.read(int(self.headers.get("Content-Length", 0)))
        inbox.put((time.time(), {k.lower(): v for k, v in self.headers.items()}, raw))
        self.send_response(200)
        self.end_headers()

    def log_message(self, *a):  # silence default access log
        pass


def ensure_webhook(pp, url):
    st, d = pp.call("GET", "/v1/notifications/webhooks")
    if st != 200:
        sys.exit(f"FATAL: cannot list webhooks: http {st} {err_name(d)}")
    for w in d.get("webhooks", []):
        if w.get("url") == url:
            say(f"using existing webhook {w['id']} for this URL")
            return w["id"]
    st, d = pp.call("POST", "/v1/notifications/webhooks", {"url": url, "event_types": [{"name": n} for n in EVENTS]})
    if st not in (200, 201):
        sys.exit(f"FATAL: cannot register webhook: http {st} {err_name(d)} {str(d.get('message', ''))[:150]}")
    say(f"registered new webhook {d['id']} for this URL")
    return d["id"]


def verify(pp, webhook_id, headers, raw):
    keys = ("auth_algo", "cert_url", "transmission_id", "transmission_sig", "transmission_time")
    try:
        f = {k: headers["paypal-" + k.replace("_", "-")] for k in keys}
    except KeyError as e:
        return False, f"missing header {e}"
    f["webhook_id"] = webhook_id
    body = json.dumps(f).encode()[:-1] + b', "webhook_event": ' + raw + b"}"  # RAW body, byte for byte
    st, d = pp.call("POST", "/v1/notifications/verify-webhook-signature", raw_body=body)
    if st != 200:
        return False, f"http {st} {err_name(d)}"
    return d.get("verification_status") == "SUCCESS", d.get("verification_status", "?")


def order_id_of(ev):
    r = ev.get("resource", {})
    if ev.get("event_type", "").startswith("CHECKOUT.ORDER"):
        return r.get("id")
    return r.get("supplementary_data", {}).get("related_ids", {}).get("order_id")


def handle(pp, webhook_id, arrived, headers, raw):
    try:
        ev = json.loads(raw)
    except ValueError:
        say("received a non-JSON delivery; ignoring")
        return
    eid, etype = ev.get("id", "?"), ev.get("event_type", "?")
    sent = None
    try:
        sent = datetime.strptime(ev["create_time"], "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=timezone.utc).timestamp()
    except (KeyError, ValueError):
        pass
    latency = f"{arrived - sent:.1f}" if sent else "?"
    ok, why = verify(pp, webhook_id, headers, raw)
    st, fetched = pp.call("GET", f"/v1/notifications/webhooks-events/{eid}")
    refetch_match = "n/a"
    if st == 200:
        refetch_match = str(fetched.get("event_type") == etype and fetched.get("resource", {}).get("id") == ev.get("resource", {}).get("id")).lower()
    oid = order_id_of(ev)
    order_status = "-"
    if oid:
        order_status, _ = pp.order_status(oid)
    verdict("webhook_event", event=eid, type=etype, verified=str(ok).lower(), verify_detail=why,
            latency_s=latency, event_refetch_http=st, refetch_matches_payload=refetch_match,
            order=oid or "-", order_regot_status=order_status)


def main():
    if len(sys.argv) < 2 or not sys.argv[1].startswith("https://"):
        sys.exit("usage: 04_webhook.py https://<public-tunnel-url>/webhooks/paypal [local_port]")
    url, port = sys.argv[1], int(sys.argv[2]) if len(sys.argv) > 2 else 8803
    env = load_env()
    pp = PP(env)
    wid = ensure_webhook(pp, url)
    if env.get("PAYPAL_WEBHOOK_ID") and env["PAYPAL_WEBHOOK_ID"] != wid:
        say("NOTE: PAYPAL_WEBHOOK_ID in .env differs from the webhook for this URL; using the URL's webhook "
            f"id {wid}. Update .env if you want the service to verify against it.")
    srv = HTTPServer(("127.0.0.1", port), Handler)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    say(f"listening on 127.0.0.1:{port} (tunnel must forward {url} here). Now run spikes 01 / 02 in another terminal.")
    start, last, n = time.time(), 0.0, 0
    try:
        while time.time() - start < TIMEOUT:
            try:
                arrived, headers, raw = inbox.get(timeout=5)
            except queue.Empty:
                if time.time() - last >= 30:
                    say(f"  ... waiting for events ({int(time.time() - start)}s of {TIMEOUT}s, {n} so far)")
                    last = time.time()
                continue
            n += 1
            handle(pp, wid, arrived, headers, raw)
    except KeyboardInterrupt:
        pass
    verdict("webhook_run", events_received=n)
    return 0 if n else 1


if __name__ == "__main__":
    sys.exit(main())
