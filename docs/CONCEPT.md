# Concept brief — Scoped Purchase Tokens for AI Agents

## Problem

AI agents are starting to buy things: flights, supplies, subscriptions. To do
it, they need payment credentials — and handing an agent your card means
unlimited blast radius. A prompt injection, a misread instruction, a rogue
loop, and the agent can spend without bound. Nobody sane gives their credit
card to a process they can't fully predict, which is why agent commerce is
stuck at "look but don't touch."

## Insight

Split the agent's action space in two:

- **Free actions** — search, compare, read reviews, check baggage rules.
  Fully autonomous, as agentic as it wants to be.
- **One gated action** — spend. It can only happen through a single-use token
  the human mints, scoped to amount, payee, and expiry.

The demo's visual thesis: the agent does fifty things, but only one of them
can move money.

## Mechanism

1. Agent shops and proposes: "United 1234, $340."
2. Human approves (see Modes). The token service mints a token:
   `{ max_amount, payee, expires_at, uses: 1 }`.
3. The service pre-builds a PayPal order (Orders v2) for the exact amount and
   payee. The agent receives only permission to **capture that order**.
4. The agent cannot alter amount or recipient — PayPal's own order object is
   the scope enforcement. Webhooks confirm capture; the ledger records it.

The agent never sees credentials. The token dies after one use or after
minutes.

## Modes

- **Verify** (human-in-the-loop): approve the exact purchase.
- **YOLO** (human-on-the-loop): approve a budget envelope; the agent picks the
  best option inside it and buys. The envelope is still a hard ceiling.

## Why it wins

- **Tech**: genuinely uses PayPal (Orders v2, Vault, Webhooks) + a real AI
  agent. Nothing decorative.
- **Design**: the approval UX is the product — two modes, one ledger.
- **Impact**: everyone building shopping agents needs this primitive.
- **Innovation**: a new trust primitive for agentic commerce, not a better
  checkout form.
- **Presentation**: the demo has a climax — attack the agent live, watch the
  envelope hold.

## Edge

The builder red-teams LLM agents. "I break agents for a living; this is the
payment primitive that makes agent spending safe" is a pitch nobody else in
the field can make.
