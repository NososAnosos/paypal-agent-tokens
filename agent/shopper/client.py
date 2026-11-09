"""The harness-side client for the token service's agent port. The ONLY spending path.

Trust notes (docs/REVIEW.md P0-3, P0-4):
- The model never sees AGENT_API_KEY. This module holds it; the model only names tools.
- The model only ever sees opaque proposal handles.
- There is no other module in agent/ that can move money; tests grep for that.
"""
import json
import os
import urllib.error
import urllib.request

BASE = os.environ.get("TOKEN_SERVICE_AGENT_URL", "http://127.0.0.1:8801")


class ServiceError(Exception):
    def __init__(self, code, reason, detail=""):
        super().__init__(f"{code}: {reason}" + (f" ({detail})" if detail else ""))
        self.reason = reason
        self.detail = detail


def _call(method, path, body=None):
    req = urllib.request.Request(
        BASE + path, method=method, data=json.dumps(body).encode() if body is not None else None,
        headers={"Authorization": f"Bearer {os.environ['AGENT_API_KEY']}", "Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=15) as r:
            return json.load(r)
    except urllib.error.HTTPError as e:
        body = json.load(e)
        raise ServiceError(e.code, body.get("error", ""), body.get("detail", "")) from None


def report(action, detail=""):  # free action, self-reported (shown grey, untrusted)
    return _call("POST", "/agent/report", {"action": action, "detail": detail})


def propose(mode, payee_id, amount, description):
    return _call("POST", "/agent/propose", dict(mode=mode, payee_id=payee_id, amount=amount,
                                                description=description))["handle"]


def status(handle):
    return _call("GET", f"/agent/status/{handle}")["state"]


def capture(handle, payee_id, amount):
    return _call("POST", "/agent/capture", dict(handle=handle, payee_id=payee_id, amount=amount))
