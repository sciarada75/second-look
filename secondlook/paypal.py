"""PayPal Disputes API client, plus a mock with the same interface.

Real client: sandbox by default. Endpoints used (all documented at
https://developer.paypal.com/docs/api/customer-disputes/v1/):
    GET  /v1/customer/disputes
    GET  /v1/customer/disputes/{id}
    POST /v1/customer/disputes/{id}/provide-evidence   (DEFEND)
    POST /v1/customer/disputes/{id}/accept-claim       (REFUND)
    POST /v1/customer/disputes/{id}/make-offer         (PARTIAL_REFUND, REPLACE)
    POST /v1/customer/disputes/{id}/send-message
    POST /v2/payments/captures/{id}/refund             (a refund of a PayPal-paid order with no dispute)

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
    def list_disputes(self, status: str = "REQUIRED_ACTION") -> List[dict]:
        # dispute_state values PayPal accepts: REQUIRED_ACTION (seller must act),
        # REQUIRED_OTHER_PARTY_ACTION, UNDER_PAYPAL_REVIEW, RESOLVED, OPEN_INQUIRIES, APPEALABLE.
        # Verified 2026-10-16: "WAITING_FOR_SELLER_RESPONSE" is a dispute *status*, not a state, and is rejected here.
        q = parse.urlencode({"dispute_state": status, "page_size": 50})
        return self._call("GET", f"/v1/customer/disputes?{q}").get("items", [])

    def get_dispute(self, dispute_id: str) -> dict:
        return self._call("GET", f"/v1/customer/disputes/{dispute_id}")

    # --- actions (each maps to one of our recommendation types) -----------
    def defend(self, dispute_id: str, note: str, tracking: Optional[dict] = None,
               evidence_type: str = "PROOF_OF_FULFILLMENT") -> dict:
        # provide-evidence is multipart/form-data: a JSON part named "input", plus optional files.
        # PROOF_OF_REFUND: the shop already refunded the order outside the dispute (a refund it marked paid).
        payload: Dict = {"evidences": [{"evidence_type": evidence_type, "notes": note}]}
        if tracking and tracking.get("tracking_number"):
            info = {"carrier_name": tracking.get("carrier") or "OTHER",
                    "tracking_number": tracking["tracking_number"]}
            if info["carrier_name"] == "OTHER" and tracking.get("carrier_name_other"):
                info["carrier_name_other"] = tracking["carrier_name_other"]
            payload["evidences"][0]["evidence_info"] = {"tracking_info": [info]}
        boundary = "----SecondLook" + str(int(time.time()))
        body = (f"--{boundary}\r\nContent-Disposition: form-data; name=\"input\"; filename=\"input.json\"\r\n"
                f"Content-Type: application/json\r\n\r\n{json.dumps(payload)}\r\n--{boundary}--\r\n").encode()
        req = request.Request(f"{self.base}/v1/customer/disputes/{dispute_id}/provide-evidence", data=body,
                              method="POST", headers={"Authorization": f"Bearer {self._auth()}",
                                                      "Content-Type": f"multipart/form-data; boundary={boundary}"})
        try:
            with request.urlopen(req, timeout=30) as r:
                raw = r.read()
                return json.loads(raw) if raw else {"status": "OK"}
        except error.HTTPError as e:
            raise RuntimeError(f"PayPal {e.code} on provide-evidence: {e.read().decode()}")

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

    def refund_capture(self, capture_id: str, amount: str, currency: str, note: str) -> dict:
        """Refund a captured PayPal payment (an order paid by PayPal, with no dispute: a shop inquiry). Payments v2.
        The capture id of an order paid through PayPal Checkout is the transaction id PayPal shows for it
        (Transaction Search, a dispute's seller_transaction_id). Money moves: only ever after a person approves."""
        return self._call("POST", f"/v2/payments/captures/{parse.quote(capture_id, safe='')}/refund",
                          {"amount": {"value": amount, "currency_code": currency}, "note_to_payer": (note or "")[:255]})

    def get_capture(self, capture_id: str) -> dict:
        """Read one captured payment (read only): how to check that a transaction id is a capture id."""
        return self._call("GET", f"/v2/payments/captures/{parse.quote(capture_id, safe='')}")

    def add_tracking(self, transaction_id: str, tracking_number: str, carrier: str = "OTHER",
                     carrier_name_other: Optional[str] = None) -> dict:
        """What the shop does when it ships: register the tracking number with PayPal.
        carrier is PayPal's code (e.g. "DHL"); "OTHER" takes the courier's name in carrier_name_other."""
        tracker = {"transaction_id": transaction_id, "tracking_number": tracking_number,
                   "status": "SHIPPED", "carrier": carrier}
        if carrier == "OTHER" and carrier_name_other:
            tracker["carrier_name_other"] = carrier_name_other
        return self._call("POST", "/v1/shipping/trackers-batch", {"trackers": [tracker]})


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

    def list_disputes(self, status: str = "REQUIRED_ACTION") -> List[dict]:
        return [c["dispute"] for c in self._load().values()
                if c["dispute"]["status"] == "WAITING_FOR_SELLER_RESPONSE"]

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

    def defend(self, dispute_id, note, tracking=None, evidence_type="PROOF_OF_FULFILLMENT"):
        return self._record(dispute_id, "provide-evidence", {"note": note, "tracking": tracking,
                                                             "evidence_type": evidence_type})

    def refund(self, dispute_id, note):
        return self._record(dispute_id, "accept-claim", {"note": note})

    def partial_refund(self, dispute_id, amount, currency, note):
        return self._record(dispute_id, "make-offer",
                            {"offer_type": "REFUND", "amount": amount, "currency": currency, "note": note})

    def replace(self, dispute_id, note):
        return self._record(dispute_id, "make-offer", {"offer_type": "REPLACEMENT_WITHOUT_REFUND", "note": note})

    def message(self, dispute_id, text):
        return self._record(dispute_id, "send-message", {"message": text})

    def refund_capture(self, capture_id, amount, currency, note):
        return {**self._record(capture_id, "capture-refund", {"capture_id": capture_id, "amount": amount,
                                                               "currency": currency, "note": note}),
                "id": f"MOCK-REFUND-{capture_id}"}


def client_from_env(root: Path):
    """Real sandbox client if PAYPAL_CLIENT_ID and PAYPAL_SECRET are set, else the mock."""
    cid, sec = os.getenv("PAYPAL_CLIENT_ID"), os.getenv("PAYPAL_SECRET")
    if cid and sec:
        return PayPalDisputes(cid, sec, os.getenv("PAYPAL_BASE", SANDBOX))
    return MockPayPal(root / "cases", root / ".tmp" / "actions.jsonl")
