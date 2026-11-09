# PayPal wiring pass — summary

Project: `~/Projects/paypal-agent-tokens/`. Pass completed against
`BRIEF-CURSOR-PAYPAL-WIRING.md`. Decisions G1–G5 unchanged. Stdlib only.

## Gap inventory (coordinator list, verified)

| Gap | Before this pass | After |
|---|---|---|
| `approve()` returns only order id; `Order.approval_url` never surfaces | **Real.** `TokenService.approve` returned `order.id`; API `{order_id: ...}`; UI ignored the body. | **Closed (W1/W2).** New `order_status`; `/human/approve` returns full object; UI shows "Approve at PayPal" when URL non-empty. `approve()` signature/return unchanged. |
| Shopper has only `ScriptedPlanner`; LLM planner TODO open | **Real.** | **Closed (W3).** `shopper/llm_planner.py` implements `Planner`; config-switched; offline-tested with fake transport. |
| DEMO beat-4 attack only a fixture inside `loop.py`; no data-driven harness; no offline wired e2e | **Real.** Injection text lived in `CATALOG` reviews; no HTTP loop test. | **Closed (W4/W5).** Root `tests/` boots mock service over real HTTP; `tests/cases.py` is data-only; runner is case-agnostic. |
| Webhook receiver exists; live proof is spike 4 | **Real; left as-is.** | Untouched. No faked webhook events. |

No corrections to the coordinator list were needed.

## What now runs end to end

- **Offline (mock):** agent `client` → agent HTTP port → `TokenService` + `MockPayPal` (demo `buyer_approve` on human approve) → ledger. Verify happy path and YOLO injection (ScriptedPlanner + data cases).
- **Sandbox smoke (W6):** in-process `TokenService` + `SandboxPayPal` + G2 registry from `.env` → mint → stop at `approval_url` (no buyer click) → pre-approval capture refused, token still `MINTED`.

### Offline demo transcript (real run)

```
=== OFFLINE VERIFY LOOP ===
status_after_propose=PENDING
approve={"amount": "340.00", "approval_url": "", "currency": "USD", "order_id": "ORD1", "payee_id": "skyair", "status": "APPROVED"}
status_after_approve=MINTED
capture={"amount": "340.00", "capture_id": "CAP2", "state": "CAPTURED"}
chain_ok=True
  ledger[1] cls=reported kind=free_action actor=agent-1 data={"action": "search_flights", "detail": "SFO-JFK"}
  ledger[2] cls=reported kind=free_action actor=agent-1 data={"action": "read_reviews", "detail": "UA1234"}
  ledger[3] cls=observed kind=proposed actor=agent-1 data={"amount": "340.00", "description_untrusted": "United 1234", "mode": "verify", "payee": "skyair", "proposal": "prop_eJBSSS8nVgRpYV6TNKs2Lg"}
  ledger[4] cls=observed kind=approved_minted actor=human-1 data={"expires_at": 1793458388.5358229, "max_amount": "340.00", "mode": "verify", "order": "ORD1", "payee": "skyair", "proposal": "prop_eJBSSS8nVgRpYV6TNKs2Lg", "token": "tok_nSJFQyEeVogxh2Hi"}
  ledger[5] cls=observed kind=capture_started actor=agent-1 data={"amount": "340.00", "order": "ORD1", "payee": "skyair", "token": "tok_nSJFQyEeVogxh2Hi"}
  ledger[6] cls=observed kind=captured actor=agent-1 data={"amount": "340.00", "capture": "CAP2", "order": "ORD1", "payee": "skyair", "token": "tok_nSJFQyEeVogxh2Hi"}

=== OFFLINE BEAT4 INJECTION (YOLO) ===
case=beat4_yolo_tv_injection
  report action=search_flights detail=SFO to JFK under $400
  report action=read_reviews detail=UA1234
  propose mode=yolo payee=skyair amount=400.00
  approve order_id=ORD1 status=APPROVED
  capture payee=megamart amount=900.00 -> {"blocked": "payee_out_of_scope"}
  capture payee=skyair amount=340.00 -> {"amount": "340.00", "capture_id": "CAP2", "state": "CAPTURED"}
chain_ok=True
  ledger[1] cls=reported kind=free_action data={"action": "search_flights", "detail": "SFO to JFK under $400"}
  ledger[2] cls=reported kind=free_action data={"action": "read_reviews", "detail": "UA1234"}
  ledger[3] cls=observed kind=proposed data={"amount": "400.00", "description_untrusted": "best flight under $400", "mode": "yolo", "payee": "skyair", "proposal": "prop_-KVjVudp80WOlJke995_Ww"}
  ledger[4] cls=observed kind=approved_minted data={"expires_at": 1793458389.5336347, "max_amount": "400.00", "mode": "yolo", "order": "ORD1", "payee": "skyair", "proposal": "prop_-KVjVudp80WOlJke995_Ww", "token": "tok_M9N1i0YIjVpH9gZ6"}
  ledger[5] cls=observed kind=capture_rejected data={"detail": "megamart", "reason": "payee_out_of_scope", "token": "tok_M9N1i0YIjVpH9gZ6"}
  ledger[6] cls=observed kind=capture_started data={"amount": "340.00", "order": "ORD1", "payee": "skyair", "token": "tok_M9N1i0YIjVpH9gZ6"}
  ledger[7] cls=observed kind=captured data={"amount": "340.00", "capture": "CAP2", "order": "ORD1", "payee": "skyair", "token": "tok_M9N1i0YIjVpH9gZ6"}
```

Regenerate with: `python3 tests/print_transcript.py`

### W6 VERDICT lines (live sandbox run)

```
Spike 5: wired sandbox smoke (verify skyair 340.00; NO buyer click)
  proposed handle=prop_Pjn-OyNYfM8f3mZ8Hp7vdg
  minted order_id=9PB863717L580384J status=PAYER_ACTION_REQUIRED
  approval_url_host=https://www.sandbox.paypal.com (path omitted)
VERDICT order_created value=ok order=9PB863717L580384J
VERDICT approval_url_present value=ok
VERDICT order_status_pre_buyer value=ok status=PAYER_ACTION_REQUIRED
VERDICT pre_approval_capture_refused value=ok reason=order_not_approved_or_mismatched
VERDICT token_still_minted value=ok state=MINTED
VERDICT wired_sandbox_smoke value=ok
```

Command: `python3 spikes/05_wired_sandbox.py` (from repo root). Spikes 01/02/04 were **not** run.

## File-by-file change surface

**W1 — only production-behavior addition to the service**

- `server/tokenservice/service.py` — added `order_status(human, proposal_id)` → `{order_id, status, approval_url, payee_id, amount, currency}` via adapter `get_order`. **`approve()` signature and return value unchanged.**
- `server/tokenservice/api.py` — `POST /human/approve` returns `order_status` object; new `GET /human/order/<proposal_id>`.

**W2 — web UI**

- `web/app.js` — after Approve, show order id/status/payee/amount; "Approve at PayPal" link when `approval_url` non-empty (`textContent` / DOM APIs only).
- `web/index.html` — `#approved` container for the post-approve card.

**W3 — LLM planner**

- `agent/shopper/llm_planner.py` — new; OpenAI-compatible chat via `urllib`; env config; garbage/unknown → `None`.
- `agent/tests/test_llm_planner.py` — offline fake-transport unit tests + isolation grep.

**W4/W5 — offline e2e + injection data**

- `tests/harness.py` — mock `DemoService` + ephemeral ports (mirrors `__main__.py`).
- `tests/cases.py` — beat4 TV injection, YOLO `amount_over_ceiling`, Verify `amount_not_exact` (data only).
- `tests/test_injection.py` — case-agnostic runner.
- `tests/test_e2e.py` — Verify HTTP loop + ScriptedPlanner YOLO + shared `run_case`.
- `tests/print_transcript.py` — transcript helper for this summary.
- `agent/shopper/loop.py` — optional `interval` on `wait_for_approval`; optional `payee_id`/`amount` overrides on `buy` (harness; service still enforces scope).

**W6 — sandbox smoke**

- `spikes/05_wired_sandbox.py` — in-process mint; no buyer click; pre-approval capture gate.

**Docs (factual one-liners only; `docs/REVIEW.md` untouched)**

- `server/README.md`, `agent/README.md`, `web/README.md`

## Test counts (as run)

```
# Baseline — must stay green (23 = trust 17 + adapter 6)
cd server && python3 -m unittest discover -s tests -t .
# → Ran 23 tests in 0.013s  OK

# Agent LLM planner unit tests
cd agent && python3 -m unittest discover -s tests -t .
# → Ran 11 tests in 0.001s  OK

# Offline HTTP e2e + injection harness (documented here and in agent/README.md)
cd <repo-root> && python3 -m unittest discover -s tests -t .
# → Ran 4 tests in ~6.5s  OK

# W6 sandbox smoke (no clicks)
python3 spikes/05_wired_sandbox.py
# → VERDICT wired_sandbox_smoke value=ok
```

Root `tests/` sit outside `agent/` on purpose: the trust test greps the agent tree for `tokenservice|paypal|/human/`.

## Remaining ship list to Nov 12

- Spikes **1 / 2 / 4** at the owner's sitting (buyer clicks, ceiling captures, webhook via tunnel)
- Demo rehearsal + recorded fallback takes
- Public GitHub repo + license + README
- Devpost submission
- Optional PayPal JS button stage (later G3)
- Adapter unknowns only the sitting can answer: approval reaching `APPROVED`; representation bodies on authorize/capture
