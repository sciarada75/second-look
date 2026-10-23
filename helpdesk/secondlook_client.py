"""The only code in Ticketbook that talks to Second Look: three calls of its public API.

Ticketbook decides nothing about money. It asks Second Look what a case is, what approving would do for
this agent (`?as=`), and sends the agent's approval — Second Look applies its limits, exactly as on its
own page. Any failure to reach Second Look raises Unavailable, which the pages show as a message.
"""
from __future__ import annotations

import json
from http.client import HTTPException
from urllib import error, parse, request


class Unavailable(Exception):
    """Second Look did not answer properly (not running, wrong address, timeout, a server error)."""


class SecondLook:
    def __init__(self, base_url: str = "http://127.0.0.1:8765", shop: str = "demo", timeout: float = 5):
        self.base, self.shop, self.timeout = base_url.rstrip("/"), shop, timeout

    def _call(self, method: str, path: str, body: dict | None = None):
        data = json.dumps(body).encode() if body is not None else None
        req = request.Request(self.base + path, data=data, method=method,
                              headers={"Content-Type": "application/json", "Cookie": f"sl_shop={self.shop}"})
        try:
            with request.urlopen(req, timeout=self.timeout) as r:
                return r.status, json.loads(r.read() or b"null")
        except error.HTTPError as e:          # a 4xx still carries Second Look's JSON answer
            if e.code >= 500:
                raise Unavailable(f"Second Look answered {e.code}") from e
            try:
                return e.code, json.loads(e.read() or b"null")
            except ValueError:
                return e.code, None
        except (error.URLError, OSError, ValueError, HTTPException) as e:
            raise Unavailable(str(e)) from e

    def customer(self, email: str) -> dict | None:
        # "@" may stay as it is in a URL path (RFC 3986); everything else that could break the path is escaped
        code, data = self._call("GET", "/api/customers/" + parse.quote(email, safe="@"))
        return data if code == 200 else None

    def case(self, dispute_id: str, as_person: str | None = None) -> dict | None:
        q = "?" + parse.urlencode({"as": as_person}) if as_person else ""
        code, data = self._call("GET", "/api/disputes/" + parse.quote(dispute_id, safe="") + q)
        return data if code == 200 else None

    def approve(self, dispute_id: str, action: str, message: str | None, by: str, review: str | None) -> tuple:
        code, data = self._call("POST", f"/api/disputes/{parse.quote(dispute_id, safe='')}/approve",
                                {"action": action, "message": message, "by": by, "review": review})
        return code, (data or {}).get("result") or f"Second Look answered {code}."
