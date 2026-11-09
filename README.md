# Scoped Purchase Tokens for AI Agents

**Working title** · PayPal AI Hackathon 2026 entry (skeleton, started 2026-10-12)

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

Skeleton + concept docs. Next: PayPal sandbox app + token service.

## Docs

- `docs/CONCEPT.md` — one-page concept brief
- `docs/ARCHITECTURE.md` — system design
- `docs/DEMO.md` — 3-minute demo video script
- `docs/PLAN.md` — build plan to the Nov 12 deadline

## Hackathon

PayPal AI Hackathon 2026 · https://paypalaihackathon.devpost.com/
Submissions close **Nov 12, 2026**. 100% online, free, solo or team.
$67,500+ in prizes. Judging: tech implementation, design, impact,
innovation, presentation.
