# The buyer-approval sitting — run sheet

**What this is:** three short test scripts ("spikes") that prove our design
works against the real PayPal sandbox (PayPal's free test world — fake money,
real API). Each spike needs you to approve test purchases in a browser,
playing the role of the buyer. That's the only part a human has to do;
everything else runs on the Legion.

**Total time:** about 30–45 minutes in one sitting, mostly waiting on
PayPal. You will click **Approve 4 times** in total (1 + 3), plus stay
present while the webhook listener runs.

**What you need:** a browser where you can open links the operator sends
you. You log in with the **demo buyer** sandbox account (a fake buyer we
created for this project). Its email and password live in the project's
`.env` file on the Legion — the operator will give you the email; the
password never leaves that file's owner, so ask the operator to sit with
the file open, or paste the password to you privately at sitting time.

**The one rule that matters:** every approval link expires after
**10 minutes**. When the operator says "click now", click promptly. If a
window expires, no harm done — we just re-run that spike.

---

## Spike 1 — a normal purchase, end to end (1 click)

- **Proves:** the basic money path works: create an order → buyer approves
  → we take the money ("capture") → taking it twice with the same receipt
  number is safely ignored (idempotency — the system can't double-charge).
- **Operator does:** runs `python3 spikes/01_order_capture.py` on the
  Legion. It creates a $5.00 test order payable to our demo merchant
  "SkyAir" and prints an approval link.
- **You do:** open the link, log in as the demo buyer, click **Approve**.
  One click.
- **Then:** the script watches the order flip to APPROVED (up to
  10 minutes), captures the $5, and replays the same capture to prove the
  duplicate is handled.
- **Done when you see:** `VERDICT capture_ok`

## Spike 2 — the YOLO ceiling (3 clicks)

- **Proves:** the budget-envelope idea ("YOLO mode"). You pre-approve a
  $400 ceiling; the agent may then buy anything up to $400 from that
  merchant but not a cent more. We test a capture of $340 (should pass),
  $401 and $460 (PayPal itself may allow a small overage — our own service
  refuses anything over the ceiling regardless; this spike measures
  PayPal's behaviour so we know both numbers), and a second capture after
  the final one (should be refused — the money is spent).
- **Operator does:** runs `python3 spikes/02_authorize_ceiling.py`. It
  creates **three** separate $400 authorizations, one per test capture.
- **You do:** approve **all three** orders as the demo buyer — three
  clicks, all inside **one shared 10-minute window**, so do them back to
  back when the operator hands you the links.
- **Done when you see:** `VERDICT capture_340_ok` plus one `attempt` line
  for each of the other captures, recording what PayPal allowed or refused.

## Spike 4 — the confirmation phone call (webhooks) (0 extra clicks)

- **Proves:** PayPal's "webhooks" — automatic notifications PayPal sends
  our server when money moves — are genuine. Anyone could fake such a
  notification, so for each real event the script checks PayPal's
  signature on it, re-fetches the event from PayPal, and re-reads the
  order before believing it. It also measures how late the notification
  arrives.
- **Operator does, before you click anything:** starts a **tunnel** (a
  temporary public web address that forwards to the Legion, needed because
  PayPal's servers must be able to reach our listener), then starts
  `python3 spikes/04_webhook.py https://<tunnel>/webhooks/paypal`, which
  registers that address with PayPal and listens. **Then** the operator
  re-runs spikes 1 and 2 in a second terminal while the listener watches —
  so this spike re-uses your spike 1 and 2 approvals if we run it in the
  same sitting: order of the sitting is therefore **4 first (listener
  up), then 1, then 2**.
- **You do:** nothing extra — your spike 1 and 2 approvals generate the
  events this spike verifies.
- **Done when you see:** for each event, a line reporting `verified`
  (signature check passed) and `latency_s` (seconds between the payment
  and PayPal's notification arriving).

---

## After the sitting

The operator fills in the RESULTS sections of spikes 1, 2 and 4 in
`docs/REVIEW.md` (spike 3's are already filled — it needed no clicks and
passed on 2026-10-31). Those results answer the last open questions about
the PayPal adapter, and the project moves from "spikes" to wiring the
agent demo end to end.
