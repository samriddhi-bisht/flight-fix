"""Twelve acceptance tests (TC1-TC12) run against the real API with the Flask test client."""
import os
import unittest

os.environ["FLIGHTFIX_TODAY"] = "2026-11-01"
from flightfix.app import create_app          # noqa: E402
from flightfix.erp import MockERP             # noqa: E402


class FlightFixTests(unittest.TestCase):
    def setUp(self):
        self.erp = MockERP()
        self.app = create_app(":memory:", connector=self.erp)
        self.c = self.app.test_client()

    # helpers ---------------------------------------------------------
    def part(self, no):
        return self.c.get("/api/parts/lookup/" + no).get_json()

    def wo_for(self, tail, code):
        self.c.post("/api/plan/generate")
        for w in self.c.get("/api/work-orders").get_json():
            if w["tail"] == tail and w["title"].startswith(code):
                return w
        self.fail("no work order for %s %s" % (tail, code))

    def start(self, wo, tech=1):
        return self.c.post("/api/work-orders/%d/start" % wo["id"], json={"technicianId": tech})

    # tests -----------------------------------------------------------
    def test_tc01_register_aircraft(self):
        r = self.c.post("/api/aircraft", json={"tail": "vt-ffz", "model": "ATR 72-600", "flightHours": 100, "cycles": 80})
        self.assertEqual(r.status_code, 201)
        self.assertEqual(r.get_json()["tail"], "VT-FFZ")
        self.assertIn("VT-FFZ", [a["tail"] for a in self.c.get("/api/aircraft").get_json()])

    def test_tc02_duplicate_tail_rejected(self):
        r = self.c.post("/api/aircraft", json={"tail": "VT-FFA", "model": "ATR 72-600"})
        self.assertEqual(r.status_code, 409)

    def test_tc03_generate_work_orders_once(self):
        first = self.c.post("/api/plan/generate").get_json()
        self.assertGreaterEqual(len(first), 3)
        self.assertEqual(self.c.post("/api/plan/generate").get_json(), [])      # no duplicates
        self.assertTrue(all(w["status"] == "OPEN" for w in first))

    def test_tc04_part_lookup(self):
        by_no = self.part("ff-p-1001")
        by_barcode = self.c.get("/api/parts/lookup/" + by_no["barcode"]).get_json()
        self.assertEqual(by_no["id"], by_barcode["id"])
        self.assertEqual(self.c.get("/api/parts/lookup/0000").status_code, 404)

    def test_tc05_adjust_up_logs_movement(self):
        p = self.part("FF-P-2001")
        r = self.c.post("/api/parts/%d/adjust" % p["id"], json={"delta": 5, "reason": "Cycle count"})
        self.assertEqual(r.get_json()["qty"], p["qty"] + 5)
        self.assertEqual(self.c.get("/api/reports/kpis").get_json()["recentMovements"][0]["reason"], "Cycle count")

    def test_tc06_adjust_below_zero_rejected(self):
        p = self.part("FF-P-2001")
        r = self.c.post("/api/parts/%d/adjust" % p["id"], json={"delta": -(p["qty"] + 1)})
        self.assertEqual(r.status_code, 409)
        self.assertEqual(self.part("FF-P-2001")["qty"], p["qty"])

    def test_tc07_issue_parts_to_started_job(self):
        wo = self.wo_for("VT-FFC", "CAB-PRS")
        self.assertEqual(self.start(wo).status_code, 200)
        g = self.part("FF-P-4002")
        r = self.c.post("/api/work-orders/%d/issue-part" % wo["id"], json={"items": [{"partId": g["id"], "qty": 2}]})
        self.assertEqual(r.status_code, 200)
        self.assertEqual(self.part("FF-P-4002")["qty"], g["qty"] - 2)
        self.assertEqual(r.get_json()["parts_cost"], 2 * g["unit_cost"])

    def test_tc08_partial_issue_rolls_back(self):
        wo = self.wo_for("VT-FFC", "CAB-PRS")
        self.start(wo)
        ok, short = self.part("FF-P-4002"), self.part("FF-P-5001")
        r = self.c.post("/api/work-orders/%d/issue-part" % wo["id"],
                        json={"items": [{"partId": ok["id"], "qty": 1}, {"partId": short["id"], "qty": 99}]})
        self.assertEqual(r.status_code, 409)
        self.assertEqual(self.part("FF-P-4002")["qty"], ok["qty"])               # first line undone
        self.assertEqual(self.c.get("/api/work-orders/%d" % wo["id"]).get_json()["parts"], [])

    def test_tc09_state_rules(self):
        wo = self.wo_for("VT-FFC", "O2-CHK")
        g = self.part("FF-P-4001")
        r = self.c.post("/api/work-orders/%d/issue-part" % wo["id"], json={"items": [{"partId": g["id"], "qty": 1}]})
        self.assertEqual(r.status_code, 409)                                      # not started yet
        self.c.post("/api/work-orders/%d/cancel" % wo["id"])
        r = self.c.post("/api/work-orders/%d/complete" % wo["id"], json={"labourHours": 2})
        self.assertEqual(r.status_code, 409)                                      # cancelled cannot complete

    def test_tc10_signoff_resets_task_and_queues_erp(self):
        wo = self.wo_for("VT-FFC", "CAB-PRS")
        self.start(wo)
        r = self.c.post("/api/work-orders/%d/complete" % wo["id"], json={"labourHours": 5.5})
        self.assertEqual(r.get_json()["status"], "COMPLETED")
        task = [i for i in self.c.get("/api/plan").get_json() if i["tail"] == "VT-FFC" and i["code"] == "CAB-PRS"][0]
        self.assertEqual(task["state"], "OK")
        box = self.c.get("/api/erp/outbox").get_json()
        self.assertEqual((box[0]["event"], box[0]["status"]), ("WORK_ORDER_COMPLETED", "PENDING"))

    def test_tc11_erp_outage_then_retry_is_idempotent(self):
        wo = self.wo_for("VT-FFC", "CAB-PRS")
        self.start(wo)
        self.c.post("/api/work-orders/%d/complete" % wo["id"], json={"labourHours": 4})
        self.erp.fail_first = 1
        self.assertEqual(self.c.post("/api/erp/sync").get_json(), {"sent": 0, "failed": 1})
        self.assertEqual(self.c.get("/api/erp/outbox").get_json()[0]["status"], "FAILED")
        self.assertEqual(self.c.post("/api/erp/sync").get_json(), {"sent": 1, "failed": 0})
        self.assertEqual(self.c.post("/api/erp/sync").get_json(), {"sent": 0, "failed": 0})  # nothing re-sent
        self.assertEqual(len(self.erp.docs), 1)

    def test_tc12_reorder_alert_then_erp_receipt(self):
        alerts = self.c.get("/api/reports/kpis").get_json()["alerts"]
        seal = [a for a in alerts if a["partNo"] == "FF-P-2001"][0]
        self.assertEqual(seal["suggestedQty"], 13)                                # max(2*8-3, 8, 1)
        self.c.post("/api/erp/receipts", json={"partNo": "FF-P-2001", "qty": 10, "poRef": "PO-7781"})
        self.assertEqual(self.part("FF-P-2001")["qty"], 13)
        alerts = self.c.get("/api/reports/kpis").get_json()["alerts"]
        self.assertNotIn("FF-P-2001", [a["partNo"] for a in alerts])


if __name__ == "__main__":
    unittest.main(verbosity=2)
