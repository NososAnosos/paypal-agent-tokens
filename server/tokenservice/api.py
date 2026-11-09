"""HTTP layer (stdlib). Three surfaces, three listeners, three credentials (REVIEW P0-3):

  agent  port: /agent/*              Bearer AGENT_API_KEY   -> Principal(agent)
  human  port: /human/*, web UI      Bearer HUMAN_API_KEY   -> Principal(human)
  webhook port: /webhooks/paypal     PayPal signature only  (expose this one via the tunnel)

The agent port serves no approval route at all, so a prompt-injected agent that
reaches it cannot approve. Bearer headers (not cookies) = no ambient CSRF.
TODO(P0-3): bind human port to localhost and require a real login before any non-demo use.
"""
import hmac
import json
import os
import threading
from decimal import Decimal
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

from .service import Forbidden, Principal, Rejected, TokenService

WEB_DIR = Path(__file__).resolve().parents[2] / "web"


def _make_handler(svc: TokenService, surface: str, key: str | None):
    class H(BaseHTTPRequestHandler):
        def log_message(self, *a): pass

        def _send(self, code, obj, ctype="application/json"):
            body = obj if isinstance(obj, bytes) else json.dumps(obj, default=str).encode()
            self.send_response(code)
            self.send_header("Content-Type", ctype)
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Cache-Control", "no-store")
            self.send_header("Content-Security-Policy", "default-src 'self'; script-src 'self'")
            self.end_headers()
            self.wfile.write(body)

        def _principal(self):
            got = self.headers.get("Authorization", "")
            if not key or not hmac.compare_digest(got.encode(), f"Bearer {key}".encode()):
                return None
            return Principal(surface, f"{surface}-1")  # TODO: per-agent ids from a key table

        def _body(self):
            n = min(int(self.headers.get("Content-Length") or 0), 64_000)
            return self.rfile.read(n)

        def do_GET(self):
            if surface == "human" and self.path in ("/", "/index.html", "/app.js"):
                name = "index.html" if self.path != "/app.js" else "app.js"
                ct = "text/html" if name.endswith("html") else "text/javascript"
                return self._send(200, (WEB_DIR / name).read_bytes(), ct)
            p = self._principal()
            if not p:
                return self._send(401, {"error": "unauthorized"})
            try:
                if self.path.startswith("/ledger"):
                    return self._send(200, {"entries": svc.ledger.entries(), "chain_ok": svc.ledger.verify()})
                if surface == "human" and self.path == "/human/pending":
                    return self._send(200, svc.pending(p))
                if surface == "human" and self.path.startswith("/human/order/"):
                    return self._send(200, svc.order_status(p, self.path.rsplit("/", 1)[1]))
                if surface == "agent" and self.path.startswith("/agent/status/"):
                    return self._send(200, {"state": svc.status(p, self.path.rsplit("/", 1)[1])})
            except (Forbidden, Rejected) as e:
                return self._send(403, {"error": str(e)})
            self._send(404, {"error": "not found"})

        def do_POST(self):
            raw = self._body()
            if surface == "webhook" and self.path == "/webhooks/paypal":
                ok = svc.handle_webhook(dict(self.headers), raw)
                return self._send(200 if ok else 400, {"ok": ok})
            p = self._principal()
            if not p:
                return self._send(401, {"error": "unauthorized"})
            try:
                d = json.loads(raw or b"{}")
                if surface == "agent":
                    if self.path == "/agent/report":
                        svc.report(p, str(d["action"]), str(d.get("detail", "")))
                        return self._send(200, {"ok": True})
                    if self.path == "/agent/propose":
                        h = svc.propose(p, mode=d["mode"], payee_id=d["payee_id"], amount=str(d["amount"]),
                                        currency=d.get("currency", "USD"), description=str(d.get("description", "")))
                        return self._send(200, {"handle": h})
                    if self.path == "/agent/capture":
                        return self._send(200, svc.capture(p, d["handle"], payee_id=d["payee_id"],
                                                           amount=str(d["amount"]), currency=d.get("currency", "USD")))
                if surface == "human":
                    if self.path == "/human/approve":
                        # approve() still returns only the order id; approval_url comes from order_status.
                        svc.approve(p, d["proposal"])
                        return self._send(200, svc.order_status(p, d["proposal"]))
                    if self.path == "/human/decline":
                        svc.decline(p, d["proposal"])
                        return self._send(200, {"ok": True})
                    # TODO(G3): /human/buyer-approved once the PayPal JS button is wired; mock mode approves here
            except Rejected as e:
                # "error" stays the stable machine code (clients assert on it);
                # the self-describing detail rides as an additive field.
                return self._send(409, {"error": e.reason, "detail": e.detail})
            except Forbidden as e:
                return self._send(403, {"error": str(e)})
            except (KeyError, ValueError, json.JSONDecodeError) as e:
                return self._send(400, {"error": f"bad request: {type(e).__name__}"})
            self._send(404, {"error": "not found"})
    return H


def serve(svc: TokenService, agent_port=8801, human_port=8802, webhook_port=8803):
    keys = {"agent": os.environ.get("AGENT_API_KEY"), "human": os.environ.get("HUMAN_API_KEY"), "webhook": None}
    ports = {"agent": agent_port, "human": human_port, "webhook": webhook_port}
    servers = []
    for surface, port in ports.items():
        s = ThreadingHTTPServer(("127.0.0.1", port), _make_handler(svc, surface, keys[surface]))
        threading.Thread(target=s.serve_forever, daemon=True).start()
        servers.append(s)
    return servers
