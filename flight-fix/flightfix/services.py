"""Maintenance planning engine, work-order lifecycle and the single stock gateway."""
import os
from datetime import date, datetime, timedelta

from . import erp

LABOUR_RATE = 3500.0                      # INR per labour hour, used for ERP cost postings
SOON = {"hours": 50, "cycles": 50, "days": 14}
PRIORITIES = ("LOW", "NORMAL", "HIGH", "AOG")


class NotFound(LookupError):
    pass


class BadRequest(ValueError):
    pass


class Conflict(RuntimeError):
    pass


def today():
    return date.fromisoformat(os.getenv("FLIGHTFIX_TODAY", date.today().isoformat()))


def now():
    return datetime.now().isoformat(sep=" ", timespec="seconds")


def one(conn, sql, args=(), what="Record"):
    row = conn.execute(sql, args).fetchone()
    if row is None:
        raise NotFound(what + " not found.")
    return row


# ---------------------------------------------------------------- maintenance planning
PLAN_SQL = """
SELECT ak.id AS aircraft_task_id, a.id AS aircraft_id, a.tail, a.flight_hours, a.cycles,
       t.id AS template_id, t.code, t.title, t.interval_hours, t.interval_days, t.interval_cycles,
       t.est_hours, ak.last_done_date, ak.last_done_hours, ak.last_done_cycles
FROM aircraft_tasks ak JOIN aircraft a ON a.id = ak.aircraft_id JOIN task_templates t ON t.id = ak.template_id"""


def due_status(r):
    """Remaining life on each limit (hours / cycles / days). The task is due on whichever limit comes first."""
    rem, interval = {}, {}
    if r["interval_hours"] is not None:
        interval["hours"] = r["interval_hours"]
        rem["hours"] = r["last_done_hours"] + r["interval_hours"] - r["flight_hours"]
    if r["interval_cycles"] is not None:
        interval["cycles"] = r["interval_cycles"]
        rem["cycles"] = r["last_done_cycles"] + r["interval_cycles"] - r["cycles"]
    if r["interval_days"] is not None:
        interval["days"] = r["interval_days"]
        rem["days"] = (date.fromisoformat(r["last_done_date"]) + timedelta(days=r["interval_days"]) - today()).days
    limit = min(rem, key=lambda k: rem[k] / interval[k])
    if any(v < 0 for v in rem.values()):
        state = "OVERDUE"
    elif any(rem[k] <= SOON[k] for k in rem):
        state = "DUE_SOON"
    else:
        state = "OK"
    return {"state": state, "limit": limit, "remaining": round(rem[limit], 1),
            "fraction_left": round(rem[limit] / interval[limit], 3)}


def plan(conn):
    """Every aircraft task with its due status, most urgent first."""
    out = []
    for r in conn.execute(PLAN_SQL):
        item = {k: r[k] for k in ("aircraft_id", "tail", "template_id", "code", "title", "est_hours")}
        item.update(due_status(r))
        out.append(item)
    rank = {"OVERDUE": 0, "DUE_SOON": 1, "OK": 2}
    out.sort(key=lambda i: (rank[i["state"]], i["fraction_left"]))
    return out


def _new_wo(conn, aircraft_id, title, kind, priority, template_id=None):
    n = conn.execute("SELECT COUNT(*) FROM work_orders").fetchone()[0]
    number = "WO-%d" % (1001 + n)
    cur = conn.execute(
        "INSERT INTO work_orders(wo_number, aircraft_id, template_id, title, kind, priority, created_at)"
        " VALUES(?,?,?,?,?,?,?)", (number, aircraft_id, template_id, title, kind, priority, now()))
    return cur.lastrowid


def generate_work_orders(conn):
    """Raise a scheduled work order for each overdue / due-soon task that has none open."""
    created = []
    with conn:
        for it in plan(conn):
            if it["state"] == "OK":
                continue
            if conn.execute("SELECT 1 FROM work_orders WHERE aircraft_id=? AND template_id=?"
                            " AND status IN ('OPEN','IN_PROGRESS')", (it["aircraft_id"], it["template_id"])).fetchone():
                continue
            wid = _new_wo(conn, it["aircraft_id"], "%s %s" % (it["code"], it["title"]), "SCHEDULED",
                          "HIGH" if it["state"] == "OVERDUE" else "NORMAL", it["template_id"])
            created.append(wid)
    return [wo_view(conn, w) for w in created]


def create_defect(conn, aircraft_id, title, priority="NORMAL"):
    if priority not in PRIORITIES:
        raise BadRequest("Priority must be one of " + ", ".join(PRIORITIES) + ".")
    if not title.strip():
        raise BadRequest("Describe the defect.")
    one(conn, "SELECT id FROM aircraft WHERE id=?", (aircraft_id,), "Aircraft")
    with conn:
        wid = _new_wo(conn, aircraft_id, title.strip(), "DEFECT", priority)
    return wo_view(conn, wid)


def create_aircraft(conn, tail, model, hours, cycles):
    if not tail or not model:
        raise BadRequest("Tail number and model are required.")
    with conn:
        aid = conn.execute("INSERT INTO aircraft(tail, model, flight_hours, cycles) VALUES(?,?,?,?)",
                           (tail, model, hours, cycles)).lastrowid
        for t in conn.execute("SELECT id FROM task_templates"):   # new aircraft start with a fresh baseline
            conn.execute("INSERT INTO aircraft_tasks(aircraft_id, template_id, last_done_date, last_done_hours,"
                         " last_done_cycles) VALUES(?,?,?,?,?)", (aid, t["id"], today().isoformat(), hours, cycles))
    return dict(one(conn, "SELECT * FROM aircraft WHERE id=?", (aid,)))


# ---------------------------------------------------------------- stock gateway
def _adjust(conn, part_id, delta, reason):
    """The only code that changes part quantities. Caller owns the transaction."""
    if delta == 0:
        raise BadRequest("Enter a quantity other than zero.")
    p = one(conn, "SELECT * FROM parts WHERE id=?", (part_id,), "Part")
    nxt = p["qty"] + delta
    if nxt < 0:
        raise Conflict("Only %d x %s in stores." % (p["qty"], p["part_no"]))
    conn.execute("UPDATE parts SET qty=? WHERE id=?", (nxt, part_id))
    conn.execute("INSERT INTO stock_movements(part_id, delta, reason, created_at) VALUES(?,?,?,?)",
                 (part_id, delta, (reason or "Manual adjustment").strip(), now()))
    return nxt


def adjust_part(conn, part_id, delta, reason):
    with conn:
        _adjust(conn, part_id, delta, reason)
    return dict(one(conn, "SELECT * FROM parts WHERE id=?", (part_id,), "Part"))


# ---------------------------------------------------------------- work-order lifecycle
def wo_view(conn, wo_id):
    wo = dict(one(conn, "SELECT w.*, a.tail, a.model, t.name AS technician FROM work_orders w"
                        " JOIN aircraft a ON a.id = w.aircraft_id LEFT JOIN technicians t ON t.id = w.technician_id"
                        " WHERE w.id=?", (wo_id,), "Work order"))
    wo["parts"] = [dict(r) for r in conn.execute(
        "SELECT p.part_no, p.name, i.qty, i.unit_cost FROM part_issues i JOIN parts p ON p.id = i.part_id"
        " WHERE i.work_order_id=? ORDER BY i.id", (wo_id,))]
    wo["parts_cost"] = round(sum(p["qty"] * p["unit_cost"] for p in wo["parts"]), 2)
    return wo


def _refresh_status(conn, aircraft_id):
    busy = conn.execute("SELECT 1 FROM work_orders WHERE aircraft_id=? AND status='IN_PROGRESS'",
                        (aircraft_id,)).fetchone()
    conn.execute("UPDATE aircraft SET status=? WHERE id=?", ("IN_MAINTENANCE" if busy else "SERVICEABLE", aircraft_id))


def start_wo(conn, wo_id, technician_id):
    wo = one(conn, "SELECT * FROM work_orders WHERE id=?", (wo_id,), "Work order")
    one(conn, "SELECT id FROM technicians WHERE id=?", (technician_id,), "Technician")
    if wo["status"] != "OPEN":
        raise Conflict("%s is already %s." % (wo["wo_number"], wo["status"].lower().replace("_", " ")))
    with conn:
        conn.execute("UPDATE work_orders SET status='IN_PROGRESS', technician_id=?, started_at=? WHERE id=?",
                     (technician_id, now(), wo_id))
        _refresh_status(conn, wo["aircraft_id"])
    return wo_view(conn, wo_id)


def issue_parts(conn, wo_id, items):
    """Issue every line or none: a shortage on any line rolls the whole request back."""
    wo = one(conn, "SELECT * FROM work_orders WHERE id=?", (wo_id,), "Work order")
    if wo["status"] != "IN_PROGRESS":
        raise Conflict("Start %s before issuing parts." % wo["wo_number"])
    if not items:
        raise BadRequest("Add at least one part.")
    with conn:
        for line in items:
            qty = int(line["qty"])
            if qty <= 0:
                raise BadRequest("Quantities must be at least 1.")
            p = one(conn, "SELECT * FROM parts WHERE id=?", (line["partId"],), "Part")
            _adjust(conn, p["id"], -qty, "Issued to " + wo["wo_number"])
            conn.execute("INSERT INTO part_issues(work_order_id, part_id, qty, unit_cost, issued_at) VALUES(?,?,?,?,?)",
                         (wo_id, p["id"], qty, p["unit_cost"], now()))
    return wo_view(conn, wo_id)


def complete_wo(conn, wo_id, labour_hours):
    wo = one(conn, "SELECT * FROM work_orders WHERE id=?", (wo_id,), "Work order")
    if wo["status"] != "IN_PROGRESS":
        raise Conflict("%s is %s, so it cannot be completed." % (wo["wo_number"], wo["status"].lower().replace("_", " ")))
    if labour_hours <= 0:
        raise BadRequest("Record the labour hours worked.")
    with conn:
        conn.execute("UPDATE work_orders SET status='COMPLETED', completed_at=?, labour_hours=? WHERE id=?",
                     (now(), labour_hours, wo_id))
        if wo["template_id"]:        # sign-off resets the task's counters to the aircraft's current usage
            a = one(conn, "SELECT * FROM aircraft WHERE id=?", (wo["aircraft_id"],), "Aircraft")
            conn.execute("UPDATE aircraft_tasks SET last_done_date=?, last_done_hours=?, last_done_cycles=?"
                         " WHERE aircraft_id=? AND template_id=?",
                         (today().isoformat(), a["flight_hours"], a["cycles"], a["id"], wo["template_id"]))
        _refresh_status(conn, wo["aircraft_id"])
        v = wo_view(conn, wo_id)
        payload = {"woNumber": v["wo_number"], "tail": v["tail"], "parts": v["parts"], "partsCost": v["parts_cost"],
                   "labourHours": labour_hours, "labourCost": round(labour_hours * LABOUR_RATE, 2)}
        payload["totalCost"] = round(payload["partsCost"] + payload["labourCost"], 2)
        erp.enqueue(conn, "WORK_ORDER_COMPLETED", "WO-COMPLETE:" + v["wo_number"], payload)
    return v


def cancel_wo(conn, wo_id):
    wo = one(conn, "SELECT * FROM work_orders WHERE id=?", (wo_id,), "Work order")
    if wo["status"] not in ("OPEN", "IN_PROGRESS"):
        raise Conflict("Only open or in-progress work orders can be cancelled.")
    with conn:
        conn.execute("UPDATE work_orders SET status='CANCELLED' WHERE id=?", (wo_id,))
        _refresh_status(conn, wo["aircraft_id"])
    return wo_view(conn, wo_id)


# ---------------------------------------------------------------- ERP inbound + KPIs
def receive_from_erp(conn, part_no, qty, po_ref):
    p = one(conn, "SELECT id FROM parts WHERE part_no=? COLLATE NOCASE", (part_no,), "Part")
    if qty <= 0:
        raise BadRequest("Receipt quantity must be at least 1.")
    return adjust_part(conn, p["id"], qty, "ERP receipt " + (po_ref or "n/a"))


def reorder_alerts(conn):
    out = []
    for p in conn.execute("SELECT * FROM parts WHERE qty <= reorder_level"):
        out.append({"partNo": p["part_no"], "name": p["name"], "onHand": p["qty"], "reorderLevel": p["reorder_level"],
                    "suggestedQty": max(p["reorder_level"] * 2 - p["qty"], p["reorder_level"], 1),
                    "supplier": p["supplier"], "leadDays": p["lead_days"]})
    out.sort(key=lambda a: a["onHand"] / max(1, a["reorderLevel"]))
    return out


def kpis(conn):
    items = plan(conn)
    total = conn.execute("SELECT COUNT(*) FROM aircraft").fetchone()[0]
    grounded = {i["aircraft_id"] for i in items if i["state"] == "OVERDUE"}
    grounded |= {r[0] for r in conn.execute("SELECT id FROM aircraft WHERE status='IN_MAINTENANCE'")}
    alerts = reorder_alerts(conn)
    done = conn.execute("SELECT COUNT(*), COALESCE(AVG(labour_hours), 0) FROM work_orders WHERE status='COMPLETED'").fetchone()
    count = lambda s: conn.execute("SELECT COUNT(*) FROM work_orders WHERE status=?", (s,)).fetchone()[0]
    return {
        "fleetSize": total, "availableAircraft": total - len(grounded),
        "availabilityPct": round((total - len(grounded)) / total * 100, 1) if total else 0,
        "overdueTasks": sum(i["state"] == "OVERDUE" for i in items),
        "dueSoonTasks": sum(i["state"] == "DUE_SOON" for i in items),
        "openWorkOrders": count("OPEN"), "inProgressWorkOrders": count("IN_PROGRESS"),
        "completedWorkOrders": done[0], "avgLabourHoursPerWO": round(done[1], 1),
        "partsIssuedCost": round(conn.execute("SELECT COALESCE(SUM(qty*unit_cost),0) FROM part_issues").fetchone()[0], 2),
        "inventoryValue": round(conn.execute("SELECT COALESCE(SUM(qty*unit_cost),0) FROM parts").fetchone()[0], 2),
        "partsBelowReorder": sum(a["onHand"] > 0 for a in alerts), "partsOutOfStock": sum(a["onHand"] == 0 for a in alerts),
        "erpPending": conn.execute("SELECT COUNT(*) FROM erp_outbox WHERE status != 'SENT'").fetchone()[0],
        "alerts": alerts,
    }
