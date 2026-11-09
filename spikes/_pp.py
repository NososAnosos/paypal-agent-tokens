"""Shared helpers for the spikes. Stdlib only. SANDBOX ONLY (host is a constant).
Raw REST on purpose: the spikes probe PayPal itself, not our adapter. Never prints secrets or headers."""
import base64
import json
import os
import sys
import time
import urllib.error
import urllib.request
import uuid

BASE = "https://api-m.sandbox.paypal.com"
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
REQUIRED = ("PAYPAL_CLIENT_ID", "PAYPAL_CLIENT_SECRET", "DEMO_MERCHANT_1_EMAIL", "DEMO_MERCHANT_2_EMAIL",
            "DEMO_BUYER_EMAIL")


def load_env(extra=()):
    path = os.environ.get("ENV_FILE", os.path.join(ROOT, ".env"))
    if not os.path.isfile(path):
        sys.exit(f"FATAL: {path} is missing. Copy .env.example to .env and fill it in.")
    env = {}
    with open(path, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line and not line.startswith("#") and "=" in line:
                k, v = line.split("=", 1)
                env[k.strip()] = v.strip().strip('"').strip("'")
    missing = [k for k in REQUIRED + tuple(extra) if not env.get(k)]
    if missing:
        sys.exit("FATAL: .env is missing: " + ", ".join(missing))
    if env.get("PAYPAL_ENV", "sandbox") != "sandbox":
        sys.exit("FATAL: PAYPAL_ENV must be 'sandbox'")
    return env


def say(msg):
    print(msg, flush=True)


def verdict(name, **kv):
    say("VERDICT " + name + " " + " ".join(f"{k}={v}" for k, v in kv.items()))


class PP:
    def __init__(self, env):
        self.env = env
        self._basic = base64.b64encode(f"{env['PAYPAL_CLIENT_ID']}:{env['PAYPAL_CLIENT_SECRET']}".encode()).decode()
        self._tok, self._exp = None, 0.0

    def _raw(self, method, url, headers, data, timeout=30):
        req = urllib.request.Request(url, data=data, headers=headers, method=method)
        try:
            with urllib.request.urlopen(req, timeout=timeout) as r:
                return r.status, r.read()
        except urllib.error.HTTPError as e:
            return e.code, e.read()
        except (urllib.error.URLError, TimeoutError, OSError) as e:
            return 0, json.dumps({"name": "NETWORK_ERROR", "message": type(e).__name__}).encode()

    def token(self):
        if self._tok and time.time() < self._exp - 60:
            return self._tok
        st, raw = self._raw("POST", BASE + "/v1/oauth2/token",
                            {"Authorization": "Basic " + self._basic,
                             "Content-Type": "application/x-www-form-urlencoded"}, b"grant_type=client_credentials")
        if st != 200:
            sys.exit(f"FATAL: OAuth failed (http {st}). Check PAYPAL_CLIENT_ID / PAYPAL_CLIENT_SECRET are sandbox app credentials.")
        d = json.loads(raw)
        self._tok, self._exp = d["access_token"], time.time() + int(d.get("expires_in", 300))
        return self._tok

    def call(self, method, path, body=None, request_id=None, raw_body=None):
        """Returns (http_status, parsed_json). Never raises on HTTP errors: the spikes WANT to see them."""
        headers = {"Authorization": "Bearer " + self.token(), "Content-Type": "application/json",
                   "Prefer": "return=representation"}
        if request_id:
            headers["PayPal-Request-Id"] = request_id
        data = raw_body if raw_body is not None else (None if body is None else json.dumps(body).encode())
        st, raw = self._raw(method, BASE + path, headers, data)
        try:
            return st, (json.loads(raw) if raw else {})
        except ValueError:
            return st, {"name": "NON_JSON_RESPONSE"}

    # -- order helpers --
    def create_order(self, intent, value, payee_email, tag):
        body = {"intent": intent,
                "purchase_units": [{"amount": {"currency_code": "USD", "value": value},
                                    "payee": {"email_address": payee_email}}],
                "payment_source": {"paypal": {"experience_context": {
                    "user_action": "PAY_NOW", "return_url": "https://example.com/return",
                    "cancel_url": "https://example.com/cancel"}}}}
        return self.call("POST", "/v2/checkout/orders", body, request_id=f"spike-{tag}-{uuid.uuid4().hex[:12]}")

    def order_status(self, order_id):
        st, d = self.call("GET", f"/v2/checkout/orders/{order_id}")
        return (d.get("status", f"HTTP_{st}") if st == 200 else f"HTTP_{st}"), d


def approval_url(order):
    return next((x["href"] for x in order.get("links", []) if x.get("rel") in ("payer-action", "approve")), "")


def err_name(d):
    issues = ",".join(x.get("issue", "") for x in d.get("details", []) if isinstance(x, dict))
    return (d.get("name", "UNKNOWN") + ("/" + issues if issues else "")).replace(" ", "_")


def wait_approved(pp, order_ids, timeout=600, poll=5):
    """Polls until every order is APPROVED. Prints on change and a heartbeat every 30s. Returns the set approved."""
    start, last_print, seen, done = time.time(), 0.0, {}, set()
    while time.time() - start < timeout:
        for oid in order_ids:
            if oid in done:
                continue
            s, _ = pp.order_status(oid)
            if s != seen.get(oid):
                say(f"  [{int(time.time() - start):>3}s] order {oid}: {s}")
                seen[oid] = s
            if s == "APPROVED":
                done.add(oid)
            elif s in ("VOIDED", "COMPLETED"):
                done.add(oid)  # nothing more to wait for; caller inspects status
        if len(done) == len(order_ids):
            return {o for o in done if seen.get(o) == "APPROVED"}
        if time.time() - last_print >= 30:
            say(f"  ... still waiting for buyer approval ({int(time.time() - start)}s of {timeout}s). "
                f"Log in as {pp.env['DEMO_BUYER_EMAIL']} at the URL(s) above and click Approve/Pay Now.")
            last_print = time.time()
        time.sleep(poll)
    say(f"  timed out after {timeout}s waiting for approval")
    return {o for o in done if seen.get(o) == "APPROVED"}
