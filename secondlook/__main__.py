"""Second Look CLI.

  python -m secondlook list                 disputes waiting for the seller
  python -m secondlook review <id>          AI judgment + guard -> recommendation
  python -m secondlook approve <id>         execute the recommended action (mock or sandbox)
  python -m secondlook eval [--judge rules|claude]   score the judge on cases/ against ground truth
"""
from __future__ import annotations

import argparse
import dataclasses
import json
import os
import sys
from pathlib import Path

from . import judge as judge_mod
from . import evidence
from .guard import apply_policy, may_approve, Decision, CHECKS, SIZE_STOPS, _partial
from .paypal import client_from_env, MockPayPal

ROOT = Path(__file__).resolve().parent.parent


def load_dotenv(path: Path) -> None:
    """Read KEY=VALUE lines from .env into this process only. Never export the Anthropic key in
    the shell: Claude Code would pick it up (see HANDOVER, Open 6). Existing env vars win."""
    if not path.exists():
        return
    for line in path.read_text().splitlines():
        line = line.strip()
        if line and not line.startswith("#") and "=" in line:
            k, v = line.split("=", 1)
            if v.strip():
                os.environ.setdefault(k.strip(), v.strip())


def load_policy() -> dict:
    return json.loads((ROOT / "policy.json").read_text())


def load_case(pp, dispute_id: str) -> dict:
    if isinstance(pp, MockPayPal):
        return pp.get_case(dispute_id)
    # Real sandbox: the dispute and the evidence come from PayPal, labelled by source.
    dispute = pp.get_dispute(dispute_id)
    return {"dispute": dispute, "seller_records": evidence.gather(pp, dispute, ROOT)}


def review(pp, dispute_id: str, backend: str) -> Decision:
    case = load_case(pp, dispute_id)
    policy = load_policy()
    case["seller_preferences"] = policy.get("seller_preferences", [])
    j = judge_mod.BACKENDS[backend](case)
    return apply_policy(j, policy, case["dispute"], case["seller_records"])


def print_decision(d: Decision, dispute: dict) -> None:
    amt = dispute["dispute_amount"]
    print(f"\n{dispute['dispute_id']}  {dispute['reason']}  {amt['value']} {amt['currency_code']}")
    if d.judgment.checks:
        print("  Checks:")
        mark = {"PASS": "✓", "FAIL": "✗", "INCONSISTENT": "!", "UNCLEAR": "?", "NOT_APPLICABLE": "–"}
        for c in d.judgment.checks:
            print(f"    {mark.get(c['result'], ' ')} {CHECKS.get(c['id'], c['id'])}: {c['finding']}")
    print(f"  AI recommends : {d.judgment.action}  (confidence {d.judgment.confidence:.2f})")
    print(f"  Why           : {d.judgment.reasoning}")
    if d.judgment.evidence_cited:
        print(f"  Evidence      : {', '.join(d.judgment.evidence_cited)}")
    if d.overridden:
        print(f"  GUARD changed it to {d.action}:")
    for n in d.reasons:
        print(f"    - {n}")
    print(f"  => Shown to seller: {d.action}  (nothing happens until you approve)")
    if d.judgment.draft_message:
        print(f"  Draft to buyer: {d.judgment.draft_message}")


def refusal(d: Decision, chosen: str) -> str:
    """Why an approval was refused, in words the seller can act on."""
    trust = [s for s in d.stops if s not in SIZE_STOPS]
    if trust:
        return (f"Not executed: this answer was held back for trust ({', '.join(trust)}), not only for its size, "
                f"so it can't be approved here. Check the case yourself first.")
    return f"Not executed: you approved {chosen}, but the recommendation is now {d.action}. Review again."


def execute(pp, d: Decision, dispute: dict, records: dict) -> dict:
    did, note = dispute["dispute_id"], d.judgment.draft_message or d.judgment.reasoning
    if d.action == "DEFEND":
        # Evidence keeps seller protection; the message keeps the buyer informed. Both, in that order.
        result = {"evidence": pp.defend(did, d.judgment.reasoning, records.get("tracking"))}
        # PayPal takes one seller message, then waits for the buyer (422 ACTION_NOT_ALLOWED_IN_CURRENT_DISPUTE_STATE).
        if d.judgment.draft_message and dispute.get("status") != "WAITING_FOR_BUYER_RESPONSE":
            result["message"] = pp.message(did, d.judgment.draft_message)
        elif d.judgment.draft_message:
            result["message"] = "not sent: PayPal is waiting for the buyer to answer your last message"
        return result
    if d.action == "REFUND":
        return pp.refund(did, note)
    if d.action == "PARTIAL_REFUND":
        # The number sent is the number the guard checked: read strictly, never above the dispute.
        # An amount that can't be read raises here and nothing is sent.
        amount = dispute["dispute_amount"]["value"]
        if d.judgment.partial_amount:
            amount = f"{min(float(amount), _partial(d.judgment.partial_amount)):.2f}"
        return pp.partial_refund(did, amount, dispute["dispute_amount"]["currency_code"], note)
    if d.action == "REPLACE":
        return pp.replace(did, note)
    if d.action == "MESSAGE":
        return pp.message(did, d.judgment.draft_message)
    return {"status": "NOT_EXECUTED", "reason": "ASK_SELLER: decide, then approve a specific action"}


def run_eval(pp, backend: str, only=None) -> int:
    if not isinstance(pp, MockPayPal):
        print("eval runs on cases/ only; unset PAYPAL_CLIENT_ID to use the mock"); return 2
    cases = sorted(pp.cases_dir.glob("*.json"))
    if only:  # cheap iteration on a few cases; a full run is still required before quoting a score
        cases = [c for c in cases if c.stem in only]
    hits, bad_money, bad_fights, asked, rows, details = 0, 0, 0, 0, [], []
    for f in cases:
        case = json.loads(f.read_text())
        truth = case["ground_truth"]["action"]
        d = review(pp, case["dispute"]["dispute_id"], backend)
        ok = d.action == truth
        hits += ok
        # the metric Claudia cares about: money given back when the truth was "defend"
        unjustified = d.action in ("REFUND", "PARTIAL_REFUND", "REPLACE") and truth == "DEFEND"
        bad_money += unjustified
        # the other costly mistake: defending a case the buyer is right about
        lost_fight = d.action == "DEFEND" and truth in ("REFUND", "PARTIAL_REFUND", "REPLACE")
        bad_fights += lost_fight
        asked += d.action == "ASK_SELLER"
        details.append({"case": case["dispute"]["dispute_id"], "truth": truth, "ai": d.judgment.action,
                        "after_guard": d.action, "confidence": d.judgment.confidence, "guard_notes": d.reasons,
                        "checks": d.judgment.checks, "reasoning": d.judgment.reasoning,
                        "draft_message": d.judgment.draft_message})
        rows.append((case["dispute"]["dispute_id"], truth, d.judgment.action, d.action,
                     "ok" if ok else ("UNJUSTIFIED REFUND" if unjustified else
                                      "LOSING FIGHT" if lost_fight else "miss")))
    print(f"\njudge={backend}  cases={len(cases)}")
    print(f"{'case':<10}{'truth':<16}{'AI said':<16}{'after guard':<16}result")
    for r in rows:
        print(f"{r[0]:<10}{r[1]:<16}{r[2]:<16}{r[3]:<16}{r[4]}")
    print(f"\ncorrect: {hits}/{len(cases)}   unjustified refunds: {bad_money}   "
          f"losing fights: {bad_fights}   routed to seller: {asked}")
    out = ROOT / ".tmp" / f"eval-{backend}-details.json"
    out.parent.mkdir(exist_ok=True)
    out.write_text(json.dumps(details, indent=1, ensure_ascii=False))
    print(f"details: {out.relative_to(ROOT)}")
    u = judge_mod.USAGE
    if u["calls"]:
        # Opus 5.5 list price: $4 / 1M input, $20 / 1M output (checked 2026-10-16)
        cost = u["input_tokens"] * 4 / 1e6 + u["output_tokens"] * 20 / 1e6
        print(f"model calls: {u['calls']}   tokens in/out: {u['input_tokens']}/{u['output_tokens']}   approx cost: ${cost:.2f}")
    return 0


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(prog="secondlook", description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("cmd", choices=["list", "review", "approve", "eval", "evidence", "ship", "serve"])
    ap.add_argument("dispute_id", nargs="?")
    ap.add_argument("--judge", default="rules", choices=list(judge_mod.BACKENDS))
    ap.add_argument("--only", nargs="*", help="eval: run only these case ids (for iterating; not a score)")
    ap.add_argument("--carrier", default="OTHER", help="ship: PayPal's carrier code; OTHER takes --carrier-name")
    ap.add_argument("--carrier-name", help="ship: the courier's name when --carrier is OTHER")
    ap.add_argument("--tracking", help="ship: the tracking number to register with PayPal")
    ap.add_argument("--action", help="approve: the action you reviewed and approve; refused if the "
                                     "recommendation shown now differs")
    a = ap.parse_args(argv)
    load_dotenv(ROOT / ".env")
    practice = a.dispute_id and (ROOT / "cases" / f"{a.dispute_id}.json").exists()
    if a.cmd == "eval" or practice:  # practice cases always run locally, never on the live sandbox
        os.environ.pop("PAYPAL_CLIENT_ID", None)
    pp = client_from_env(ROOT)
    mode = "MOCK (cases/)" if isinstance(pp, MockPayPal) else "PayPal sandbox"

    if a.cmd == "list":
        print(f"[{mode}] disputes waiting for you:")
        for d in pp.list_disputes():
            print(f"  {d['dispute_id']}  {d['reason']:<40} {d['dispute_amount']['value']} {d['dispute_amount']['currency_code']}  due {d.get('seller_response_due_date','?')}")
        return 0
    if a.cmd == "eval":
        return run_eval(pp, a.judge, a.only)
    if a.cmd == "serve":
        from .web import serve
        serve()
        return 0
    if not a.dispute_id:
        ap.error("dispute_id required")
    case = load_case(pp, a.dispute_id)
    if a.cmd == "evidence":
        print(json.dumps(case["seller_records"], indent=1, ensure_ascii=False)); return 0
    if a.cmd == "ship":
        if not a.tracking:
            ap.error("--tracking required")
        print(json.dumps(pp.add_tracking(case["dispute"]["disputed_transactions"][0]["seller_transaction_id"],
                                         a.tracking, a.carrier, a.carrier_name), ensure_ascii=False))
        return 0
    d = review(pp, a.dispute_id, a.judge)
    print(f"[{mode}] judge={a.judge}")
    print_decision(d, case["dispute"])
    if a.cmd == "approve":
        # The seller approves a specific action they have seen, never "whatever the model says now".
        if not a.action:
            print("\nNot executed: say which action you approve, e.g. --action MESSAGE"); return 2
        if not may_approve(d.action, a.action, d.judgment.action, d.stops):
            print("\n" + refusal(d, a.action)); return 2
        d = dataclasses.replace(d, action=a.action)  # ASK_SELLER + MESSAGE sends the drafted question
        print("\nexecuting:", json.dumps(execute(pp, d, case["dispute"], case["seller_records"]), ensure_ascii=False))
    return 0


if __name__ == "__main__":
    sys.exit(main())
