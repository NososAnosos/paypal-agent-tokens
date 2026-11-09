# Architecture

## Components

```
┌──────────┐      propose       ┌──────────────┐      mint       ┌────────────┐
│  Agent   │ ─────────────────▶ │ Token service │ ─────────────▶ │  PayPal    │
│ (shops,  │                    │  (scope,      │  create order  │  Sandbox   │
│  compares)│ ◀───────────────── │   ledger)    │                │ Orders v2  │
└──────────┘   token (1-time)   └──────────────┘                └────────────┘
      │                                │                               │
      │ capture                        │ webhook                       │
      └────────────────────────────────┴───────────────────────────────┘
                                       ▼
                                 ┌──────────┐
                                 │   Web    │  approval UI (Verify/YOLO),
                                 │ approval │  action ledger feed
                                 │   UI     │
                                 └──────────┘
```

- **`server/`** — token service (Node or Python): mints/scopes/validates
  tokens, builds PayPal orders, verifies captures, keeps the audit ledger.
- **`agent/`** — shopping agent loop: free actions unlimited; the only
  spending path is presenting a token to the service.
- **`web/`** — approval UI: the proposed purchase card, Verify / YOLO /
  Decline, and the live ledger (free actions grey, the one gated purchase
  gold).

## Token

```json
{
  "id": "tok_A3F9",
  "mode": "verify | yolo",
  "max_amount": "340.00",
  "currency": "USD",
  "payee": "united.com",
  "expires_at": "2026-11-01T12:10:00Z",
  "uses_remaining": 1
}
```

- Verify mode: `max_amount` and `payee` are exact.
- YOLO mode: `max_amount` is a ceiling; `payee` may be an allowlist or a
  category ("airlines"). The service validates every capture against the
  envelope before calling PayPal.
- TTL in minutes (default 10). Single use enforced server-side; the PayPal
  order can only be captured once anyway.

## Trust properties

1. The agent never holds credentials — only a token for a pre-built order.
2. Scope is enforced by PayPal's order object, not by prompt discipline.
3. Every spend is a ledger entry: who approved, what scope, what happened.
4. A compromised agent's maximum damage is one approved purchase.

## PayPal primitives used

- Orders v2 — create / capture (the scope enforcement)
- Webhooks — capture confirmation, dispute signals
- Vault (Payment Method Tokens) — if the human pre-links a funding source
- Transaction Search — ledger reconciliation (stretch)

## Sandbox notes

- All development against the PayPal Developer sandbox.
- Credentials live in `.env` (see `.env.example`) — never in the repo.
