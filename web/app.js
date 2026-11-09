// Approval UI skeleton. All dynamic text goes through textContent (REVIEW P0-1/P2: no HTML from the agent).
// TODO(P0-3): replace the prompt() key with a real human login.
// TODO(G3): later stage — PayPal JS SDK button; until then, sandbox uses the approval_url link.
const key = sessionStorage.key || (sessionStorage.key = prompt("human key"));
const api = (path, body) => fetch(path, {
  method: body ? "POST" : "GET",
  headers: {Authorization: "Bearer " + key, "Content-Type": "application/json"},
  body: body && JSON.stringify(body)}).then(r => r.json());

const el = (tag, text, cls) => { const e = document.createElement(tag); e.textContent = text; if (cls) e.className = cls; return e; };

function showApprovedOrder(res) {
  // Persist after the pending card disappears: service-derived order facts + staged G3 link.
  const box = document.getElementById("approved");
  const c = el("div", "", "card");
  c.append(el("div", `Order: ${res.order_id || ""}`));
  c.append(el("div", `Status: ${res.status || ""}`));
  c.append(el("div", `Pay to: ${res.payee_id || ""} · ${res.amount || ""} ${res.currency || ""}`));
  if (res.approval_url) {
    const a = document.createElement("a");
    a.textContent = "Approve at PayPal";
    a.href = res.approval_url;
    a.rel = "noopener noreferrer";
    a.target = "_blank";
    c.append(a);
  }
  box.replaceChildren(c);
}

async function renderPending() {
  const box = document.getElementById("pending"); box.replaceChildren();
  for (const p of await api("/human/pending")) {
    const c = el("div", "", "card");
    // service-derived facts first (these are what you are approving)
    c.append(el("div", `${p.mode.toUpperCase()}: ${p.mode === "yolo" ? "up to " : ""}${p.amount} ${p.currency}`));
    c.append(el("div", `Pay to: ${p.payee_id} (${p.payee_account})`));
    c.append(el("div", `Expires: ${new Date(p.expires_at * 1000).toLocaleTimeString()}  ·  1 use`));
    c.append(el("div", "Agent says (untrusted): " + p.agent_says_untrusted, "untrusted"));
    for (const [label, path] of [["Approve", "/human/approve"], ["Decline", "/human/decline"]]) {
      const b = el("button", p.mode === "yolo" && label === "Approve" ? "Approve YOLO budget" : label);
      b.onclick = async () => {
        const res = await api(path, {proposal: p.proposal});
        if (label === "Approve" && res && res.order_id) showApprovedOrder(res);
        refresh();
      };
      c.append(b);
    }
    box.append(c);
  }
}

async function renderLedger() {
  const {entries, chain_ok} = await api("/ledger");
  document.getElementById("chain").textContent = chain_ok ? "(chain ok)" : "(CHAIN BROKEN)";
  const box = document.getElementById("ledger"); box.replaceChildren();
  for (const e of entries.slice().reverse()) {
    let cls = e.cls;                                   // reported = grey, never gold
    if (e.cls === "observed" && e.kind === "captured") cls = "gold";
    if (e.kind.endsWith("rejected") || e.kind.endsWith("failed")) cls = "blocked";
    box.append(el("div", `${e.kind} · ${e.actor} · ${JSON.stringify(e.data)}`, cls));
  }
}

const refresh = () => Promise.all([renderPending(), renderLedger()]);
refresh(); setInterval(refresh, 2000);
