"""Token service core: propose -> approve(mint) -> capture, with every trust
property enforced here, in one place, against SQLite compare-and-set updates.

Principals (REVIEW P0-3): agent and human methods demand different Principal
kinds. The HTTP layer maps separate credentials/ports onto them.

Token lifecycle:  MINTED -> CAPTURING -> CAPTURED | FAILED | UNKNOWN
  MINTED->CAPTURING is the single-use gate: one atomic UPDATE that also checks
  expiry. Nothing ever moves a token back to MINTED. A declined capture burns
  the token (REVIEW G4, recommended default). UNKNOWN is settled only by
  reconcile(), which asks PayPal.
"""
import json
import secrets
import sqlite3
import threading
import time
from dataclasses import dataclass
from decimal import Decimal

from . import ledger as L
from .money import parse_amount
from .paypal import AUTHORIZE, CAPTURE, PayPalAdapter, PayPalError, PayPalUnknown

VERIFY, YOLO = "verify", "yolo"


class Forbidden(Exception): ...
class Rejected(Exception):
    """Policy refusal. .reason is a stable machine code shown in the ledger and to the agent."""
    def __init__(self, reason, detail=""):
        super().__init__(f"{reason}: {detail}" if detail else reason)
        self.reason = reason
        self.detail = detail


@dataclass(frozen=True)
class Principal:
    kind: str  # "agent" | "human" | "system"
    id: str


@dataclass
class Config:
    proposal_ttl: float = 300.0      # unanswered proposal -> EXPIRED (= deny)
    token_ttl: float = 600.0         # starts at APPROVAL, not proposal (REVIEW P1-4)
    max_open_proposals: int = 3      # per agent (REVIEW P1-5)
    max_proposals_per_agent: int = 20
    max_single_amount: Decimal = Decimal("1000.00")
    daily_cap: Decimal = Decimal("1500.00")  # across all approvals (REVIEW P1-6)


# Payee registry (REVIEW P1-1): payee_id -> PayPal sandbox business account.
# The agent can only name an id; it can never supply an account or a category.
DEFAULT_PAYEES = {"skyair": "skyair-merchant@example.com", "megamart": "megamart-merchant@example.com"}

SCHEMA = """
CREATE TABLE IF NOT EXISTS proposals(
  id TEXT PRIMARY KEY, agent_id TEXT NOT NULL, mode TEXT NOT NULL,
  payee_id TEXT NOT NULL, amount TEXT NOT NULL, currency TEXT NOT NULL,
  description TEXT NOT NULL, state TEXT NOT NULL,
  created_at REAL NOT NULL, expires_at REAL NOT NULL);
CREATE TABLE IF NOT EXISTS tokens(
  id TEXT PRIMARY KEY, proposal_id TEXT NOT NULL UNIQUE, agent_id TEXT NOT NULL,
  mode TEXT NOT NULL, payee_id TEXT NOT NULL, max_amount TEXT NOT NULL, currency TEXT NOT NULL,
  expires_at REAL NOT NULL, state TEXT NOT NULL, uses_remaining INTEGER NOT NULL,
  order_id TEXT NOT NULL, capture_id TEXT, approved_by TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS webhook_events(event_id TEXT PRIMARY KEY);
"""


def _need(p: Principal, kind: str):
    if p.kind != kind:
        raise Forbidden(f"{kind} principal required")


class TokenService:
    def __init__(self, paypal: PayPalAdapter, db_path=":memory:", config: Config | None = None,
                 payees: dict | None = None, clock=time.time):
        self.paypal, self.cfg, self.clock = paypal, config or Config(), clock
        self.payees = dict(payees or DEFAULT_PAYEES)
        self.lock = threading.RLock()  # guards the connection only; never held across PayPal calls
        self.db = sqlite3.connect(db_path, check_same_thread=False, isolation_level=None)
        with self.lock:
            self.db.executescript(SCHEMA)
        self.ledger = L.Ledger(self.db, self.lock, clock)

    # ---- helpers ----
    def _q(self, sql, args=()):
        with self.lock:
            return self.db.execute(sql, args)

    def _obs(self, kind, actor, **data):
        self.ledger.append(L.OBSERVED, kind, actor, data)

    # ---- agent surface ----
    def report(self, agent: Principal, action: str, detail: str = ""):
        """Free action, self-reported. Class 'reported': never trusted, never gold."""
        _need(agent, "agent")
        self.ledger.append(L.REPORTED, "free_action", agent.id, {"action": action[:64], "detail": detail[:200]})

    def propose(self, agent: Principal, *, mode, payee_id, amount, currency="USD", description="") -> str:
        """Returns an opaque handle (the only thing the model should ever see)."""
        _need(agent, "agent")
        if mode not in (VERIFY, YOLO):
            raise Rejected("bad_mode", "valid modes are 'verify' and 'yolo'")
        if payee_id not in self.payees:
            self._obs("proposal_rejected", agent.id, reason="unknown_payee")
            raise Rejected("unknown_payee")
        amt = parse_amount(amount, currency)  # for YOLO this is the CEILING the human is asked to approve
        if amt > self.cfg.max_single_amount:
            self._obs("proposal_rejected", agent.id, reason="over_single_cap")
            raise Rejected("over_single_cap")
        now = self.clock()
        open_n = self._q("SELECT COUNT(*) FROM proposals WHERE agent_id=? AND state='PROPOSED' AND expires_at>?",
                         (agent.id, now)).fetchone()[0]
        total_n = self._q("SELECT COUNT(*) FROM proposals WHERE agent_id=?", (agent.id,)).fetchone()[0]
        if open_n >= self.cfg.max_open_proposals or total_n >= self.cfg.max_proposals_per_agent:
            self._obs("proposal_rejected", agent.id, reason="proposal_rate_limit")
            raise Rejected("proposal_rate_limit")
        pid = "prop_" + secrets.token_urlsafe(16)
        self._q("INSERT INTO proposals VALUES(?,?,?,?,?,?,?,?,?,?)",
                (pid, agent.id, mode, payee_id, str(amt), currency, description[:500], "PROPOSED",
                 now, now + self.cfg.proposal_ttl))
        self._obs("proposed", agent.id, proposal=pid, mode=mode, payee=payee_id, amount=str(amt),
                  description_untrusted=description[:200])
        return pid

    def status(self, agent: Principal, handle: str) -> str:
        _need(agent, "agent")
        p = self._q("SELECT state,expires_at FROM proposals WHERE id=? AND agent_id=?", (handle, agent.id)).fetchone()
        if not p:
            raise Rejected("unknown_handle")
        if p[0] != "PROPOSED":
            if p[0] == "APPROVED":
                return self._q("SELECT state FROM tokens WHERE proposal_id=?", (handle,)).fetchone()[0]
            return p[0]
        return "EXPIRED" if p[1] <= self.clock() else "PENDING"

    def capture(self, agent: Principal, handle: str, *, payee_id: str, amount, currency="USD") -> dict:
        """The ONLY spending path. Everything about the purchase is re-checked here;
        nothing the agent says is believed beyond naming what it wants to buy."""
        _need(agent, "agent")
        row = self._q("""SELECT id,mode,payee_id,max_amount,currency,expires_at,state,order_id
                         FROM tokens WHERE proposal_id=? AND agent_id=?""", (handle, agent.id)).fetchone()
        if not row:  # wrong agent, unapproved, or made-up handle: indistinguishable on purpose
            self._obs("capture_rejected", agent.id, reason="no_token_for_handle")
            raise Rejected("no_token_for_handle")
        tid, mode, t_payee, t_max, t_cur, t_exp, t_state, order_id = row
        if t_state != "MINTED":  # fast path only; the CAS in step 3 is the authority
            return self._reject(agent, tid, "token_already_used")

        # 1. scope (does not burn the token: a probing agent learns nothing and costs nothing;
        #    a burning policy would let an injection DoS the legitimate purchase)
        try:
            amt = parse_amount(amount, currency)
        except ValueError as e:
            return self._reject(agent, tid, "bad_amount", str(e))
        if currency != t_cur:
            return self._reject(agent, tid, "currency_mismatch")
        if payee_id != t_payee:
            return self._reject(agent, tid, "payee_out_of_scope", payee_id)
        ceiling = Decimal(t_max)
        if mode == VERIFY and amt != ceiling:
            return self._reject(agent, tid, "amount_not_exact", str(amt))
        if mode == YOLO and amt > ceiling:
            return self._reject(agent, tid, "amount_over_ceiling", str(amt))

        # 2. buyer actually approved at PayPal (REVIEW P1-2); definite answer or fail closed
        try:
            order = self.paypal.get_order(order_id)
        except Exception:
            return self._reject(agent, tid, "order_unavailable")
        if order.status != "APPROVED" or order.payee_account != self.payees[t_payee] or order.currency != t_cur:
            return self._reject(agent, tid, "order_not_approved_or_mismatched", order.status)
        if order.amount != ceiling:
            return self._reject(agent, tid, "order_amount_mismatch")

        # 3. the single-use gate: atomic, expiry-checked, one winner
        with self.lock:
            cur = self.db.execute("""UPDATE tokens SET state='CAPTURING', uses_remaining=0
                                     WHERE id=? AND state='MINTED' AND uses_remaining=1 AND expires_at>?""",
                                  (tid, self.clock()))
            won = cur.rowcount == 1
            st = self.db.execute("SELECT state,expires_at FROM tokens WHERE id=?", (tid,)).fetchone()
        if not won:
            reason = "token_expired" if st[0] == "MINTED" and st[1] <= self.clock() else "token_already_used"
            return self._reject(agent, tid, reason)
        self._obs("capture_started", agent.id, token=tid, order=order_id, amount=str(amt), payee=t_payee)

        # 4. call PayPal exactly once, idempotent on the token id
        try:
            cap = self.paypal.capture(order_id=order_id, request_id=tid, amount=amt)
        except PayPalError as e:
            self._settle(tid, "FAILED", None)
            self._obs("capture_failed", agent.id, token=tid, reason=str(e))
            raise Rejected("paypal_declined", str(e))
        except PayPalUnknown as e:
            self._settle(tid, "UNKNOWN", None)
            self._obs("capture_unknown", agent.id, token=tid, reason=str(e))
            raise Rejected("outcome_unknown", "will be reconciled; do not retry")

        # 5. defense in depth: PayPal's answer must match scope before we call it a success
        if (cap.status != "COMPLETED" or cap.amount != amt or cap.currency != t_cur
                or cap.payee_account != self.payees[t_payee]):
            self._settle(tid, "UNKNOWN", cap.id)
            self._obs("capture_mismatch", agent.id, token=tid, capture=cap.id)
            raise Rejected("capture_mismatch")
        self._settle(tid, "CAPTURED", cap.id)
        self._obs("captured", agent.id, token=tid, capture=cap.id, amount=str(cap.amount),
                  payee=t_payee, order=order_id)
        return {"state": "CAPTURED", "capture_id": cap.id, "amount": str(cap.amount)}

    def _reject(self, agent, tid, reason, detail=""):
        self._obs("capture_rejected", agent.id, token=tid, reason=reason, detail=detail[:100])
        raise Rejected(reason, detail)

    def _settle(self, tid, state, capture_id):
        self._q("UPDATE tokens SET state=?, capture_id=COALESCE(?,capture_id) WHERE id=? AND state='CAPTURING'",
                (state, capture_id, tid))

    # ---- human surface ----
    def pending(self, human: Principal) -> list[dict]:
        """Everything on the card is service-derived. Agent text is labelled untrusted (REVIEW P0-1)."""
        _need(human, "human")
        rows = self._q("""SELECT id,agent_id,mode,payee_id,amount,currency,description,expires_at
                          FROM proposals WHERE state='PROPOSED' AND expires_at>? ORDER BY created_at""",
                       (self.clock(),)).fetchall()
        return [dict(proposal=r[0], agent=r[1], mode=r[2], payee_id=r[3], payee_account=self.payees[r[3]],
                     amount=r[4], currency=r[5], expires_at=r[7],
                     agent_says_untrusted=r[6]) for r in rows]

    def decline(self, human: Principal, proposal_id: str):
        _need(human, "human")
        cur = self._q("UPDATE proposals SET state='DECLINED' WHERE id=? AND state='PROPOSED' AND expires_at>?",
                      (proposal_id, self.clock()))
        if cur.rowcount != 1:
            raise Rejected("not_pending")
        self._obs("declined", human.id, proposal=proposal_id)

    def approve(self, human: Principal, proposal_id: str) -> str:
        """Human approval -> mint. CAS makes double-click / two tabs mint at most one token."""
        _need(human, "human")
        now = self.clock()
        p = self._q("SELECT agent_id,mode,payee_id,amount,currency FROM proposals WHERE id=?",
                    (proposal_id,)).fetchone()
        if not p:
            raise Rejected("unknown_proposal")
        agent_id, mode, payee_id, amount, currency = p
        amt = Decimal(amount)
        spent = sum(Decimal(r[0]) for r in self._q(
            "SELECT max_amount FROM tokens WHERE expires_at>? AND "
            "(state IN ('CAPTURING','CAPTURED','UNKNOWN') OR (state='MINTED' AND expires_at>?))",
            (now - 86400, now)).fetchall())  # approximates "last 24h" via expiry (TODO: store approved_at)
        if spent + amt > self.cfg.daily_cap:
            self._obs("approval_blocked", human.id, proposal=proposal_id, reason="daily_cap")
            raise Rejected("daily_cap")
        cur = self._q("UPDATE proposals SET state='APPROVED' WHERE id=? AND state='PROPOSED' AND expires_at>?",
                      (proposal_id, now))
        if cur.rowcount != 1:
            raise Rejected("not_pending")
        # Verify: exact CAPTURE order. YOLO: AUTHORIZE order for the ceiling (REVIEW P0-2a).
        intent = CAPTURE if mode == VERIFY else AUTHORIZE
        try:
            order = self.paypal.create_order(request_id=proposal_id, intent=intent,
                                             payee_account=self.payees[payee_id], amount=amt, currency=currency)
        except Exception as e:
            self._q("UPDATE proposals SET state='FAILED' WHERE id=?", (proposal_id,))
            self._obs("mint_failed", human.id, proposal=proposal_id, reason=type(e).__name__)
            raise Rejected("order_creation_failed")
        tid = "tok_" + secrets.token_urlsafe(12)
        self._q("INSERT INTO tokens VALUES(?,?,?,?,?,?,?,?,?,?,?,NULL,?)",
                (tid, proposal_id, agent_id, mode, payee_id, str(amt), currency,
                 now + self.cfg.token_ttl, "MINTED", 1, order.id, human.id))
        self._obs("approved_minted", human.id, proposal=proposal_id, token=tid, mode=mode, payee=payee_id,
                  max_amount=str(amt), order=order.id, expires_at=now + self.cfg.token_ttl)
        # TODO(G3): the human must now approve ORDER `order.id` at PayPal (JS SDK button). Return its id to the UI.
        return order.id

    def order_status(self, human: Principal, proposal_id: str) -> dict:
        """Human-surface view of the PayPal order minted for an approved proposal (REVIEW G3).
        Does not change approve()'s return value; the UI fetches approval_url via this."""
        _need(human, "human")
        row = self._q("""SELECT order_id, payee_id, max_amount, currency FROM tokens WHERE proposal_id=?""",
                      (proposal_id,)).fetchone()
        if not row:
            raise Rejected("no_order_for_proposal")
        order_id, payee_id, amount, currency = row
        order = self.paypal.get_order(order_id)
        return {
            "order_id": order.id,
            "status": order.status,
            "approval_url": order.approval_url or "",
            "payee_id": payee_id,
            "amount": amount,
            "currency": currency,
        }

    # ---- reconciliation & webhooks ----
    def reconcile(self, system: Principal, token_id: str) -> str:
        """Settle an UNKNOWN capture by asking PayPal. Never returns a token to MINTED."""
        _need(system, "system")
        t = self._q("SELECT order_id,state,max_amount FROM tokens WHERE id=?", (token_id,)).fetchone()
        if not t or t[1] != "UNKNOWN":
            raise Rejected("not_unknown")
        order = self.paypal.get_order(t[0])
        new = "CAPTURED" if order.status == "COMPLETED" and order.captured > 0 else "FAILED"
        # TODO: for FAILED require PayPal to confirm no capture exists before settling
        self._q("UPDATE tokens SET state=? WHERE id=? AND state='UNKNOWN'", (new, token_id))
        self._obs("reconciled", system.id, token=token_id, result=new)
        return new

    def handle_webhook(self, headers: dict, raw_body: bytes) -> bool:
        """A webhook is a HINT. It cannot create a CAPTURED state, only annotate one we already know."""
        if not self.paypal.verify_webhook({k.lower(): v for k, v in headers.items()}, raw_body):
            self._obs("webhook_rejected", "paypal", reason="bad_signature")
            return False
        try:
            ev = json.loads(raw_body)
            event_id, etype = str(ev["id"]), str(ev["event_type"])
            capture_id = str(ev.get("resource", {}).get("id", ""))
        except (ValueError, KeyError, AttributeError):
            self._obs("webhook_rejected", "paypal", reason="malformed")
            return False
        try:
            self._q("INSERT INTO webhook_events VALUES(?)", (event_id,))
        except sqlite3.IntegrityError:
            return True  # duplicate delivery, already handled
        known = self._q("SELECT id FROM tokens WHERE capture_id=?", (capture_id,)).fetchone()
        # TODO: re-GET the order from PayPal before trusting anything in the payload
        self._obs("webhook", "paypal", event=event_id, type=etype, capture=capture_id,
                  matches_token=known[0] if known else None)
        return True
