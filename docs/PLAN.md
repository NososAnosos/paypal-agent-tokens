# Build plan — to Nov 12, 2026

Deadline: submissions close **Nov 12, 2026** (Devpost). Judging Dec 1–15,
winners ~Dec 21. ~4 weeks from skeleton.

## Week 1 — by Oct 19: money moves

- [ ] PayPal Developer sandbox app + credentials in `.env`
- [ ] Token service skeleton: mint / validate / single-use enforcement
- [ ] Create + capture a sandbox order end to end (no agent yet)
- [ ] Webhook receiver logging captures

## Week 2 — by Oct 26: agent + approval

- [ ] Shopping agent loop (flight search demo scenario)
- [ ] Approval UI: proposed-purchase card, Verify / YOLO / Decline
- [ ] Ledger feed: free actions grey, gated purchase gold
- [ ] YOLO envelope validation against captures

## Week 3 — by Nov 2: adversarial + polish

- [ ] Prompt-injection test harness vs. the envelope (red-team pass)
- [ ] Decline paths + UX for blocked attempts
- [ ] UI polish, empty/error states
- [ ] Demo script rehearsal, shot list check

## Week 4 — by Nov 12: ship

- [ ] Record + edit the under-3-minute demo video
- [ ] Public GitHub repo, README, screenshots
- [ ] Devpost submission: description, repo, video, tools used

## Open questions

- Exact vs. budget tokens: both modes planned; cut one if time pinches
  (keep Verify — it's the clearer story).
- Agent model: local (Legion) vs. API — decide in Week 1 by cost/latency.
- Stretch: Transaction Search reconciliation, Vault funding source.
