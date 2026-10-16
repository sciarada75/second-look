"""PayPal Disputes API client, plus a mock with the same interface.

Real client: sandbox by default. Endpoints used (all documented at
https://developer.paypal.com/docs/api/customer-disputes/v1/):
    GET  /v1/customer/disputes
    GET  /v1/customer/disputes/{id}
    POST /v1/customer/disputes/{id}/provide-evidence   (DEFEND)
    POST /v1/customer/disputes/{id}/accept-claim       (REFUND)
    POST /v1/customer/disputes/{id}/make-offer         (PARTIAL_REFUND, REPLACE)
    POST /v1/customer/disputes/{id}/send-message

Mock client: reads cases/*.json and appends every action to .tmp/actions.jsonl,
so the whole flow runs without credentials. Same method names, same payloads.
"""
from __future__ import annotations

import base64
import json
import os
import time
from pathlib import Path
from typing import Dict, List, Optional
from urllib import request, parse, error

SANDBOX = "https://api-m.sandbox.paypal.com"


class PayPalDisputes:
    def __init__(self, client_id: str, secret: str, base: str = SANDBOX):
        self.base, self._id, self._secret = base, client_id, secret
        self._token: Optional[str] = None
        self._token_exp = 0.0

    # --- auth -------------------------------------------------------------
    def _auth(self) -> str:
        if self._token and time.time() < self._token_exp - 60:
            return self._token
        creds = base64.b64encode(f"{self._id}:{self._secret}".encode()).decode()
        req = request.Request(
            f"{self.base}/v1/oauth2/token",
            data=b"grant_type=client_credentials",
            headers={"Authorization": f"Basic {creds}",
                     "Content-Type": "application/x-www-form-urlencoded"},
        )
        with request.urlopen(req, timeout=30) as r:
            body = json.load(r)
        self._token = body["access_token"]
        self._token_exp = time.time() + int(body.get("expires_in", 3600))
        return self._token

    def _call(self, method: str, path: str, payload: Optional[dict] = None) -> dict:
        data = json.dumps(payload).encode() if payload is not None else None
        req = request.Request(f"{self.base}{path}", data=data, method=method,
                              headers={"Authorization": f"Bearer {self._auth()}",
                                       "Content-Type": "application/json"})
        try:
            with request.urlopen(req, timeout=30) as r:
                raw = r.read()
                return json.loads(raw) if raw else {}
        except error.HTTPError as e:  # surface PayPal's error body, it is useful
            raise RuntimeError(f"PayPal {e.code} on {method} {path}: {e.read().decode()}")

    # --- reads ------------------------------------------------------------
    def list_disputes(self, status: str = "WAITING_FOR_SELLER_RESPONSE") -> List[dict]:
        q = parse.urlencode({"dispute_state": status, "page_size": 50})
        return self._call("GET", f"/v1/customer/disputes?{q}").get("items", [])

    def get_dispute(self, dispute_id: str) -> dict:
        return self._call("GET", f"/v1/customer/disputes/{dispute_id}")

    # --- actions (each maps to one of our recommendation types) -----------
    def defend(self, dispute_id: str, note: str, tracking: Optional[dict] = None) -> dict:
        payload: Dict = {"evidences": [{"evidence_type": "PROOF_OF_FULFILLMENT",
                                        "notes": note}]}
        if tracking:
            payload["evidences"][0]["evidence_info"] = {"tracking_info": [tracking]}
        return self._call("POST", f"/v1/customer/disputes/{dispute_id}/provide-evidence", payload)

    def refund(self, dispute_id: str, note: str) -> dict:
        return self._call("POST", f"/v1/customer/disputes/{dispute_id}/accept-claim",
                          {"note": note, "accept_claim_type": "REFUND"})

    def partial_refund(self, dispute_id: str, amount: str, currency: str, note: str) -> dict:
        return self._call("POST", f"/v1/customer/disputes/{dispute_id}/make-offer",
                          {"note": note, "offer_type": "REFUND",
                           "offer_amount": {"currency_code": currency, "value": amount}})

    def replace(self, dispute_id: str, note: str) -> dict:
        return self._call("POST", f"/v1/customer/disputes/{dispute_id}/make-offer",
                          {"note": note, "offer_type": "REPLACEMENT_WITHOUT_REFUND"})

    def message(self, dispute_id: str, text: str) -> dict:
        return self._call("POST", f"/v1/customer/disputes/{dispute_id}/send-message",
                          {"message": text})


class MockPayPal:
    """Same interface, no network. Disputes come from cases/, actions go to a log."""

    def __init__(self, cases_dir: Path, log: Path):
        self.cases_dir, self.log = Path(cases_dir), Path(log)
        self.log.parent.mkdir(parents=True, exist_ok=True)

    def _load(self) -> Dict[str, dict]:
        out = {}
        for f in sorted(self.cases_dir.glob("*.json")):
            case = json.loads(f.read_text())
            out[case["dispute"]["dispute_id"]] = case
        return out

    def list_disputes(self, status: str = "WAITING_FOR_SELLER_RESPONSE") -> List[dict]:
        return [c["dispute"] for c in self._load().values()
                if c["dispute"]["status"] == status]

    def get_dispute(self, dispute_id: str) -> dict:
        return self._load()[dispute_id]["dispute"]

    def get_case(self, dispute_id: str) -> dict:
        """Mock-only: the dispute plus the seller's own records and ground truth."""
        return self._load()[dispute_id]

    def _record(self, dispute_id: str, action: str, payload: dict) -> dict:
        entry = {"ts": time.strftime("%Y-%m-%dT%H:%M:%S"), "dispute_id": dispute_id,
                 "action": action, "payload": payload}
        with self.log.open("a") as fh:
            fh.write(json.dumps(entry) + "\n")
        return {"status": "MOCK_OK", **entry}

    def defend(self, dispute_id, note, tracking=None):
        return self._record(dispute_id, "provide-evidence", {"note": note, "tracking": tracking})

    def refund(self, dispute_id, note):
        return self._record(dispute_id, "accept-claim", {"note": note})

    def partial_refund(self, dispute_id, amount, currency, note):
        return self._record(dispute_id, "make-offer",
                            {"offer_type": "REFUND", "amount": amount, "currency": currency, "note": note})

    def replace(self, dispute_id, note):
        return self._record(dispute_id, "make-offer", {"offer_type": "REPLACEMENT_WITHOUT_REFUND", "note": note})

    def message(self, dispute_id, text):
        return self._record(dispute_id, "send-message", {"message": text})


def client_from_env(root: Path):
    """Real sandbox client if PAYPAL_CLIENT_ID and PAYPAL_SECRET are set, else the mock."""
    cid, sec = os.getenv("PAYPAL_CLIENT_ID"), os.getenv("PAYPAL_SECRET")
    if cid and sec:
        return PayPalDisputes(cid, sec, os.getenv("PAYPAL_BASE", SANDBOX))
    return MockPayPal(root / "cases", root / ".tmp" / "actions.jsonl")
