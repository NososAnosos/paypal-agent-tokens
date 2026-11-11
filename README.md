# Scoped Purchase Tokens for AI Agents

**PayPal AI Hackathon 2026 entry** · Built and measured against the live PayPal
sandbox. All money in this project is sandbox money; the sandbox host is
hard-coded and there is no live-money code path.

AI agents that buy things shouldn't hold your credit card. This project is a
trust primitive for agentic commerce: single-use, scoped purchase tokens that
let an agent complete exactly one approved purchase — and nothing else.

## The idea in 30 seconds

- The agent does everything free: search, compare, read reviews.
- Spending is a **gated action**. The human mints a token scoped to amount,
  payee, and expiry — single use.
- The agent presents the token to capture a pre-built PayPal order. It cannot
  change the amount or the recipient. Prompt-inject it all you want: the worst
  it can do is the one purchase you approved.

## Modes

- **Verify** — the agent proposes the exact purchase ("United 1234, $340");
  you tap approve; a token is minted for precisely that.
- **YOLO** — you set the envelope ("best option under $400"); the agent picks
  and buys autonomously inside it. The token scope is the ceiling either way.

## Status

Working end to end and measured against the real PayPal sandbox:

- A live LLM agent ran the full Verify loop (search, read reviews, propose,
  approval, buy) and captured $340.00 with a prompt injection sitting in its
  context — delivered, and ignored.
- The YOLO ceiling was measured, not assumed: captures of $401 and $460
  landed on a $400 authorization, inside PayPal's documented overcapture
  tolerance (115% or $75, whichever is less). PayPal is therefore not the
  ceiling enforcer — the token service is, and it refuses any capture above
  the envelope before money moves.
- Webhooks are verified by signature on the raw body, then re-fetched and
  cross-checked against the order before the ledger believes them.
- 44 automated tests green, including the $900 out-of-scope television
  capture being refused while the in-scope flight still captured.
- The design went through an adversarial review before the wiring was
  finished; the review, findings and all, is in `docs/REVIEW.md`.

Run evidence (order IDs, verdict lines, spike scripts) lives in `docs/`,
`spikes/`, and the sitting logs at the repo root.

## Docs

- `docs/CONCEPT.md` — one-page concept brief
- `docs/ARCHITECTURE.md` — system design
- `docs/REVIEW.md` — adversarial review and spike results
- `docs/SITTING.md` — how the live sandbox runs are driven
- `docs/DEMO.md` — 3-minute demo video script
- `docs/PLAN.md` — build plan to the Nov 12 deadline

## Hackathon

PayPal AI Hackathon 2026 · https://paypalaihackathon.devpost.com/
Submissions close **Nov 12, 2026**. 100% online, free, solo or team.
$67,500+ in prizes. Judging: tech implementation, design, impact,
innovation, presentation.
