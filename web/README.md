# web/ — approval UI skeleton

Static `index.html` + `app.js`, served by the service's human port. Pending card (service-derived facts first, agent text boxed as untrusted), Approve / Approve YOLO budget / Decline, and a ledger feed (grey = agent-reported, gold = service-observed capture, red = blocked). After Approve, the UI shows the order id and — when `approval_url` is non-empty (sandbox) — an "Approve at PayPal" link (staged G3). TODO: PayPal JS button for buyer approval (later G3 stage), real login (P0-3).
