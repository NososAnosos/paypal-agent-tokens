"""Shared offline HTTP harness: mock-backed TokenService + real agent/human ports.

Mirrors server/tokenservice/__main__.py demo behavior (human approve + mock
buyer_approve). Stdlib only. Used by e2e and injection tests.
"""
import json
import os
import sys
import threading
import time
import urllib.error
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "server"))
sys.path.insert(0, str(ROOT / "agent"))

from tokenservice.api import serve  # noqa: E402
from tokenservice.mock_paypal import MockPayPal  # noqa: E402
from tokenservice.service import TokenService  # noqa: E402


class DemoService(TokenService):
    """Mock stands in for the human's PayPal login (REVIEW G3), same as __main__.py."""

    def approve(self, human, proposal_id):
        order_id = super().approve(human, proposal_id)
        self.paypal.buyer_approve(order_id)
        return order_id


def _free_ports(n=3):
    """Bind ephemeral ports then release them for serve() to reuse."""
    import socket
    socks, ports = [], []
    for _ in range(n):
        s = socket.socket()
        s.bind(("127.0.0.1", 0))
        ports.append(s.getsockname()[1])
        socks.append(s)
    for s in socks:
        s.close()
    return ports


class WiredService:
    """Boot agent/human/webhook listeners; configure shopper.client env."""

    def __init__(self, agent_key="test-agent-key", human_key="test-human-key"):
        self.agent_key = agent_key
        self.human_key = human_key
        self.pp = MockPayPal()
        self.svc = DemoService(self.pp)
        self.ports = _free_ports(3)
        self.servers = None
        self._env_backup = {}

    def start(self):
        os.environ["AGENT_API_KEY"] = self.agent_key
        os.environ["HUMAN_API_KEY"] = self.human_key
        self.servers = serve(self.svc, *self.ports)
        agent_url = f"http://127.0.0.1:{self.ports[0]}"
        # shopper.client reads BASE at import time — force-refresh.
        import shopper.client as client
        self._env_backup = {
            "BASE": client.BASE,
            "TOKEN_SERVICE_AGENT_URL": os.environ.get("TOKEN_SERVICE_AGENT_URL"),
        }
        os.environ["TOKEN_SERVICE_AGENT_URL"] = agent_url
        client.BASE = agent_url
        time.sleep(0.05)  # let threads bind
        return self

    def stop(self):
        if self.servers:
            for s in self.servers:
                s.shutdown()
                s.server_close()
        import shopper.client as client
        if "BASE" in self._env_backup:
            client.BASE = self._env_backup["BASE"]
        prev = self._env_backup.get("TOKEN_SERVICE_AGENT_URL")
        if prev is None:
            os.environ.pop("TOKEN_SERVICE_AGENT_URL", None)
        else:
            os.environ["TOKEN_SERVICE_AGENT_URL"] = prev

    def __enter__(self):
        return self.start()

    def __exit__(self, *exc):
        self.stop()

    @property
    def human_base(self):
        return f"http://127.0.0.1:{self.ports[1]}"

    def human_call(self, method, path, body=None):
        data = None if body is None else json.dumps(body).encode()
        req = urllib.request.Request(
            self.human_base + path, method=method, data=data,
            headers={"Authorization": f"Bearer {self.human_key}",
                     "Content-Type": "application/json"})
        try:
            with urllib.request.urlopen(req, timeout=10) as r:
                return r.status, json.load(r)
        except urllib.error.HTTPError as e:
            return e.code, json.load(e)

    def ledger(self):
        code, body = self.human_call("GET", "/ledger")
        assert code == 200, body
        return body

    def approve_pending(self):
        code, pending = self.human_call("GET", "/human/pending")
        assert code == 200, pending
        assert pending, "expected a pending proposal"
        code, res = self.human_call("POST", "/human/approve", {"proposal": pending[0]["proposal"]})
        assert code == 200, res
        return res

    def auto_approve_until(self, stop: threading.Event, interval=0.15):
        """Background: approve any pending proposal (demo human)."""
        while not stop.is_set():
            try:
                code, pending = self.human_call("GET", "/human/pending")
                if code == 200 and pending:
                    self.human_call("POST", "/human/approve", {"proposal": pending[0]["proposal"]})
            except Exception:
                pass
            stop.wait(interval)
