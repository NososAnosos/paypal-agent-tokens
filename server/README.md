# server/ — token service

Python 3, stdlib only (sqlite3 gives atomic compare-and-set for single-use, `decimal` for exact money, `http.server` is enough for three tiny surfaces; zero install friction for judges).

- `tokenservice/service.py` — propose / approve(mint) / `order_status` / capture / reconcile / webhook. All trust checks live here. `approve()` still returns only the order id; `order_status` surfaces `approval_url` for the staged G3 buyer link.
- `tokenservice/paypal.py` — adapter interface + `SandboxPayPal` (sandbox host only). `mock_paypal.py` for offline tests.
- `tokenservice/ledger.py` — append-only, hash-chained; `observed` vs `reported` entries.
- `tokenservice/api.py` — agent / human / webhook listeners on separate ports and credentials. Human: `POST /human/approve` returns the `order_status` object; `GET /human/order/<proposal_id>` is the same shape.

Run tests (from `server/`): `python3 -m unittest discover -s tests -t .` → 23 OK (trust 17 + adapter 6).
Run mock service: `AGENT_API_KEY=... HUMAN_API_KEY=... python3 -m tokenservice` then open http://127.0.0.1:8802
Sandbox: `python3 -m tokenservice --sandbox` (reads `../.env`).
