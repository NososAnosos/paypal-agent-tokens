# BRIEF — PayPal wiring pass: agent ↔ service ↔ UI end to end (sandbox mode)

Project: ~/Projects/paypal-agent-tokens/ (Python 3, **stdlib only** — no new
dependencies anywhere). Deadline: Devpost Nov 12, 2026, 3:00 PM ET.

Read first: docs/CONCEPT.md, docs/ARCHITECTURE.md, docs/REVIEW.md,
docs/DEMO.md, docs/PLAN.md, and the READMEs in server/, agent/, web/.
Decisions G1–G5 in docs/REVIEW.md are SETTLED (authorize-ceiling, registry
payees, staged buyer approval at `Order.approval_url`, declined capture burns
the token, single-shot YOLO). Build to them; do not relitigate.

## Hard boundaries

- **No human buyer clicks.** Do NOT run spikes/01, spikes/02, spikes/04 — they
  are staged for the owner's sitting. Nobody approves any PayPal order.
- **No secrets in code, logs, or the summary.** Keys come from the environment
  or `../.env` via the existing `load_dotenv`. Never print a key value.
- **Decided token-service semantics do not change.** The one service change
  allowed is W1 below; flag anything else you believe is forced, in the
  summary, instead of silently changing behavior.
- Baseline that must stay green: `cd server && python3 -m unittest discover
  -s tests -t .` → 23 tests OK (trust 17 + adapter 6). Note:
  `tests/test_trust.py` calls `svc.approve(HUMAN, h)` and uses the return
  value as the order id — that contract must not break.
- Do not edit docs/REVIEW.md. Factual one-line updates to server/README.md and
  agent/README.md where this pass makes them stale are welcome.

## Gap inventory (verified by the coordinator's read — build against this)

- `TokenService.approve()` returns only the order id; the sandbox adapter's
  `Order` already carries `approval_url`, but it never surfaces. The staged
  G3 flow (human approves at `Order.approval_url`) therefore dead-ends in
  the UI: web/app.js calls `/human/approve` and ignores the response.
- The shopper has only `ScriptedPlanner`; the README's TODO (LLM-backed
  planner) is open. `shopper/client.py` is and must remain the only spending
  path; the model must never see credentials or token secrets.
- The DEMO beat-4 attack exists only as a fixture inside loop.py. There is
  no data-driven injection harness and no offline end-to-end test that runs
  the wired loop (agent → HTTP → service → adapter → ledger).
- The webhook receiver exists (service.handle_webhook + webhook port) and
  stays as-is; the live webhook proof is spike 4 at the sitting. Do not fake
  webhook events.

## Work items

### W1 — surface the buyer-approval link (the one service seam change)
- Add a human-surface service method (e.g. `order_status(human, proposal_id)`)
  that returns `{order_id, status, approval_url, payee_id, amount, currency}`
  for an approved proposal, reading the order back through the adapter
  (`get_order`). Do NOT change `approve()`'s signature or return value.
- API: `/human/approve` response gains `approval_url` (fetched via the new
  method; empty string in mock mode is correct). Add `GET
  /human/order/<proposal_id>` returning the same object.
- This is the pass's only production-behavior addition to the service; call
  it out in the summary as such.

### W2 — web UI: close the staged G3 loop
- After a successful Approve, the card shows the order id and, when
  `approval_url` is non-empty, an "Approve at PayPal" link to it (sandbox
  mode). Keep the existing discipline: all dynamic text via `textContent`,
  service-derived facts first, agent text boxed as untrusted. No PayPal JS
  SDK in this pass (that is the later G3 stage).

### W3 — LLM planner for the shopper (config-switched, offline-testable)
- New module in agent/shopper/ implementing the existing `Planner` protocol
  with an OpenAI-compatible chat client built on `urllib` (match client.py's
  style). The planner turns model output into the EXISTING tool Actions only
  (search_flights, read_reviews, propose, wait_for_approval, buy). It never
  holds the agent key and never calls the service directly — loop.run_tool
  remains the only execution path.
- Config from environment only: `SHOPPER_MODEL_PROVIDER` = `openrouter`
  (default) or `local`; `SHOPPER_MODEL` = model name (configurable, with a
  documented default per provider); OpenRouter base
  `https://openrouter.ai/api/v1` using `OPENROUTER_API_KEY` from the
  environment; local base `http://127.0.0.1:18434/v1` (llama.cpp, no key).
  Read keys from env at call time; never hardcode, never log them.
- Robustness: unparseable model output or an unknown tool name → return
  None (stop) rather than guessing. Cap history length sent to the model.
- Offline unit tests with an injected fake transport: provider/config
  resolution, tool-call → Action mapping, garbage output → None, and a test
  that the planner module contains no reference to the service credentials
  or capture endpoint (it proposes Actions; client.py spends).

### W4 — offline end-to-end integration tests (HTTP + mock adapter)
New tests (unittest, discoverable; if placed outside server/tests, document
the exact command in the summary and in agent/README.md):
- Boot `api.serve` on non-default ports against a mock-backed service
  (mirror __main__.py's demo behavior: human approve + mock buyer_approve),
  drive `shopper.client` over real HTTP through a full **Verify** loop:
  report free actions → propose verify skyair 340.00 → human approves via
  the human port → status leaves PENDING → capture → CAPTURED.
- Assert on the ledger via `/ledger`: free actions are class `reported`,
  the capture is class `observed` kind `captured`, `chain_ok` is true, and
  no `reported` entry is ever the captured one.
- Full **YOLO** loop with ScriptedPlanner: envelope 400.00 on skyair;
  TV900 buy blocked; UA1234 buy captured. (This overlaps W5's canonical
  case; W5 is the data-driven harness — reuse one implementation, don't
  build two.)

### W5 — injection harness as data (DEMO beat 4, deterministic, offline)
- Represent attack cases as DATA (a cases module or JSON in the new test
  package): each case = catalog/task setup + ordered agent steps (including
  explicit capture attempts with payee/amount) + expected outcome per step
  (blocked with a specific service reason code, or captured).
- Canonical case (beat 4): YOLO envelope "best flight under $400" on
  skyair; the poisoned review drives a buy of the $900 MegaMart TV →
  expect blocked, reason `payee_out_of_scope`; then the in-scope UA1234
  purchase still captures (scope rejections must not burn the token).
- Second case proving the ceiling independently: a capture attempt naming
  skyair with an inflated amount (e.g. 460.00) inside the same envelope →
  blocked, reason `amount_over_ceiling`.
- Third case: Verify mode, capture at any amount ≠ the exact approved
  amount → blocked, reason `amount_not_exact`.
- The harness runs against the wired loop offline (mock adapter). Adding a
  case must require editing only the data, not the runner.

### W6 — sandbox smoke, stopping at the approval point (NO clicks)
- New script `spikes/05_wired_sandbox.py` (stdlib, reads ../.env like the
  other spikes): builds `TokenService` in-process with `SandboxPayPal` and
  the G2 registry from .env; agent proposes verify skyair 340.00; human
  approves (service-level mint) → assert: order created, `approval_url`
  non-empty, order status is CREATED/PAYER_ACTION_REQUIRED.
- Then attempt the capture BEFORE any buyer approval and assert it is
  cleanly refused by the service (reason `order_not_approved_or_mismatched`)
  and the token is still MINTED afterwards (the pre-approval gate costs
  nothing and burns nothing).
- Print only VERDICT lines and non-secret progress (order id + status are
  fine; never print .env values). Run it once and record the verdicts in
  the summary. This creates real sandbox orders that simply lapse — that
  is expected and already the pattern from spike 3.

## Deliverable — PAYPAL-WIRING-SUMMARY.md in the project root

- Gap inventory: what was real vs stubbed before this pass (use the
  coordinator's list; correct it where your read differs, with evidence).
- What now runs end to end, with an **offline demo transcript**: the actual
  captured output of the full Verify loop and the canonical injection case
  (ledger lines + step results), pasted from a real run.
- W6's VERDICT lines from the live sandbox smoke.
- File-by-file change surface; W1 flagged as the only service change.
- Test counts: the full offline suite(s) as run by you (commands included),
  with the 23-test baseline called out as still green.
- Remaining ship list to Nov 12: spikes 1/2/4 at the owner's sitting
  (buyer clicks, ceiling captures, webhook via tunnel), demo rehearsal +
  recorded fallback takes, public GitHub repo + license + README,
  Devpost submission, optional PayPal JS button stage, and the adapter's
  remaining spike unknowns (approval reaching APPROVED; representation
  bodies) that only the sitting can answer.
