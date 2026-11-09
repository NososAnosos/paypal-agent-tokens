"""python3 -m tokenservice [--sandbox]   (from server/)
Default: MockPayPal. --sandbox: the real PayPal sandbox adapter; credentials and demo merchants from ../.env."""
import os
import sys
import time

from .api import serve
from .mock_paypal import MockPayPal
from .paypal import SandboxPayPal, load_dotenv
from .service import TokenService

if __name__ == "__main__":
    if not (os.environ.get("AGENT_API_KEY") and os.environ.get("HUMAN_API_KEY")):
        raise SystemExit("set AGENT_API_KEY and HUMAN_API_KEY (different random values)")
    db = os.environ.get("LEDGER_DB", "tokens.db")
    if "--sandbox" in sys.argv:
        env_path = os.environ.get("ENV_FILE", "../.env")
        e = load_dotenv(env_path)
        # Payee registry (REVIEW G2): ids map to our own sandbox business accounts, never to agent input.
        payees = {"skyair": e["DEMO_MERCHANT_1_EMAIL"], "megamart": e["DEMO_MERCHANT_2_EMAIL"]}
        # TODO(G3): until the PayPal JS button exists, the human approves the order as DEMO_BUYER_EMAIL at
        # Order.approval_url; capture() then sees status APPROVED.
        svc = TokenService(SandboxPayPal.from_env(env_path), db_path=db, payees=payees)
        label = "PayPal SANDBOX"
    else:
        class DemoService(TokenService):
            def approve(self, human, proposal_id):  # mock stands in for the human's PayPal login (REVIEW G3)
                order_id = super().approve(human, proposal_id)
                self.paypal.buyer_approve(order_id)
                return order_id

        svc = DemoService(MockPayPal(), db_path=db)
        label = "mock PayPal"
    serve(svc)
    print(f"agent :8801  human+web :8802  webhook :8803  ({label})")
    while True:
        time.sleep(3600)
