"""ERP integration: transactional outbox (FlightFix -> ERP) and inbound receipts (ERP -> FlightFix)."""
import json
import os
import urllib.request
from datetime import datetime

MAX_ATTEMPTS = 5


def enqueue(conn, event, idem_key, payload):
    """Queue an ERP posting inside the caller's transaction, so it exists only if the work committed."""
    conn.execute(
        "INSERT OR IGNORE INTO erp_outbox(event, idem_key, payload, created_at) VALUES(?,?,?,?)",
        (event, idem_key, json.dumps(payload), datetime.now().isoformat(sep=" ", timespec="seconds")))


def sync(conn, connector):
    """Push every PENDING / FAILED posting. Failures are kept and retried on the next sync."""
    rows = conn.execute(
        "SELECT * FROM erp_outbox WHERE status != 'SENT' AND attempts < ? ORDER BY id", (MAX_ATTEMPTS,)).fetchall()
    sent = failed = 0
    for r in rows:
        try:
            doc = connector.post(r["event"], r["idem_key"], json.loads(r["payload"]))
            conn.execute("UPDATE erp_outbox SET status='SENT', erp_doc=?, attempts=attempts+1, last_error=NULL,"
                         " sent_at=? WHERE id=?", (doc, datetime.now().isoformat(sep=" ", timespec="seconds"), r["id"]))
            sent += 1
        except Exception as e:  # network or ERP error: keep the row for retry
            conn.execute("UPDATE erp_outbox SET status='FAILED', attempts=attempts+1, last_error=? WHERE id=?",
                         (str(e), r["id"]))
            failed += 1
    conn.commit()
    return {"sent": sent, "failed": failed}


class MockERP:
    """Stand-in for SAP / Oracle: returns a document number and de-duplicates on the idempotency key."""

    def __init__(self, fail_first=0):
        self.docs, self.fail_first, self.calls = {}, fail_first, 0

    def post(self, event, idem_key, payload):
        self.calls += 1
        if self.fail_first > 0:
            self.fail_first -= 1
            raise ConnectionError("ERP unreachable (simulated outage)")
        if idem_key not in self.docs:
            self.docs[idem_key] = "ERP-%d" % (4500000000 + len(self.docs) + 1)
        return self.docs[idem_key]


class HttpERP:
    """Generic REST connector. Set FLIGHTFIX_ERP_URL to your ERP gateway (not exercised in the demo)."""

    def __init__(self, url, token=""):
        self.url, self.token = url, token

    def post(self, event, idem_key, payload):
        req = urllib.request.Request(
            self.url, data=json.dumps({"event": event, "payload": payload}).encode(), method="POST",
            headers={"Content-Type": "application/json", "Idempotency-Key": idem_key,
                     "Authorization": "Bearer " + self.token})
        with urllib.request.urlopen(req, timeout=10) as resp:
            return json.loads(resp.read())["documentNumber"]


def from_env():
    url = os.getenv("FLIGHTFIX_ERP_URL")
    return HttpERP(url, os.getenv("FLIGHTFIX_ERP_TOKEN", "")) if url else MockERP()
