"""FlightFix REST API (Flask). 21 JSON endpoints plus the static single-page UI."""
import os
import sqlite3
import threading

from flask import Flask, g, jsonify, request

from . import db, erp as erpmod, seed as seed_mod, services as svc


def create_app(db_path="data/flightfix.db", connector=None, seed=True):
    if db_path != ":memory:":
        os.makedirs(os.path.dirname(db_path) or ".", exist_ok=True)
    conn = db.connect(db_path)
    if seed:
        seed_mod.seed(conn)
    erp = connector or erpmod.from_env()
    app = Flask(__name__, static_folder="static", static_url_path="")
    app.config.update(DB=conn, ERP=erp)
    lock = threading.RLock()  # one shared SQLite connection: serialise requests

    @app.before_request
    def _enter():
        lock.acquire()
        g.locked = True

    @app.teardown_request
    def _exit(_exc):
        if g.pop("locked", False):
            lock.release()

    rows = lambda cur: [dict(r) for r in cur.fetchall()]

    def body():
        return request.get_json(silent=True) or {}

    def req(d, key):
        if d.get(key) in (None, ""):
            raise svc.BadRequest("%s is required." % key)
        return d[key]

    def num(d, key, cast, default=None):
        try:
            return cast(d[key]) if d.get(key) not in (None, "") else default
        except (TypeError, ValueError):
            raise svc.BadRequest("%s must be a number." % key)

    @app.errorhandler(svc.NotFound)
    def _404(e):
        return jsonify(message=str(e)), 404

    @app.errorhandler(svc.Conflict)
    def _409(e):
        return jsonify(message=str(e)), 409

    @app.errorhandler(sqlite3.IntegrityError)
    def _dup(_e):
        return jsonify(message="That tail number, part number, barcode or licence is already in use."), 409

    @app.errorhandler(ValueError)
    def _400(e):
        return jsonify(message=str(e)), 400

    @app.get("/")
    def home():
        return app.send_static_file("index.html")

    # ---- fleet and planning
    @app.get("/api/aircraft")
    def aircraft_list():
        return jsonify(rows(conn.execute("SELECT * FROM aircraft ORDER BY tail")))

    @app.post("/api/aircraft")
    def aircraft_add():
        d = body()
        return jsonify(svc.create_aircraft(conn, str(req(d, "tail")).strip().upper(), str(req(d, "model")).strip(),
                                           num(d, "flightHours", float, 0.0), num(d, "cycles", int, 0))), 201

    @app.get("/api/plan")
    def plan_view():
        return jsonify(svc.plan(conn))

    @app.post("/api/plan/generate")
    def plan_generate():
        return jsonify(svc.generate_work_orders(conn)), 201

    # ---- work orders
    @app.get("/api/work-orders")
    def wo_list():
        sql, args = "SELECT id FROM work_orders WHERE 1=1", []
        if request.args.get("status"):
            sql += " AND status=?"
            args.append(request.args["status"].upper())
        if request.args.get("technicianId"):
            sql += " AND technician_id=?"
            args.append(int(request.args["technicianId"]))
        return jsonify([svc.wo_view(conn, r["id"]) for r in conn.execute(sql + " ORDER BY id DESC", args)])

    @app.post("/api/work-orders")
    def wo_defect():
        d = body()
        return jsonify(svc.create_defect(conn, num(d, "aircraftId", int), str(req(d, "title")),
                                         d.get("priority", "NORMAL"))), 201

    @app.get("/api/work-orders/<int:wid>")
    def wo_one(wid):
        return jsonify(svc.wo_view(conn, wid))

    @app.post("/api/work-orders/<int:wid>/start")
    def wo_start(wid):
        return jsonify(svc.start_wo(conn, wid, num(body(), "technicianId", int)))

    @app.post("/api/work-orders/<int:wid>/issue-part")
    def wo_issue(wid):
        return jsonify(svc.issue_parts(conn, wid, body().get("items", [])))

    @app.post("/api/work-orders/<int:wid>/complete")
    def wo_complete(wid):
        return jsonify(svc.complete_wo(conn, wid, num(body(), "labourHours", float, 0.0)))

    @app.post("/api/work-orders/<int:wid>/cancel")
    def wo_cancel(wid):
        return jsonify(svc.cancel_wo(conn, wid))

    # ---- spare parts
    @app.get("/api/parts")
    def parts_list():
        q = "%" + request.args.get("q", "").lower() + "%"
        return jsonify(rows(conn.execute(
            "SELECT * FROM parts WHERE lower(part_no || ' ' || name || ' ' || COALESCE(category, '')) LIKE ?"
            " ORDER BY part_no", (q,))))

    @app.post("/api/parts")
    def parts_add():
        d = body()
        with conn:
            pid = conn.execute(
                "INSERT INTO parts(part_no, barcode, name, category, unit_cost, reorder_level, supplier, lead_days)"
                " VALUES(?,?,?,?,?,?,?,?)",
                (str(req(d, "partNo")).strip().upper(), d.get("barcode") or None, str(req(d, "name")).strip(),
                 d.get("category"), num(d, "unitCost", float, 0.0), num(d, "reorderLevel", int, 0),
                 d.get("supplier"), num(d, "leadDays", int, 7))).lastrowid
        return jsonify(dict(conn.execute("SELECT * FROM parts WHERE id=?", (pid,)).fetchone())), 201

    @app.post("/api/parts/<int:pid>/adjust")
    def parts_adjust(pid):
        d = body()
        return jsonify(svc.adjust_part(conn, pid, num(d, "delta", int, 0), d.get("reason")))

    @app.get("/api/parts/lookup/<code>")
    def parts_lookup(code):
        c = code.strip()
        p = conn.execute("SELECT * FROM parts WHERE part_no=? COLLATE NOCASE OR barcode=?", (c, c)).fetchone()
        if p is None:
            raise svc.NotFound('Nothing matches "%s". Check the part number or barcode.' % c)
        return jsonify(dict(p))

    # ---- technicians (mobile)
    @app.get("/api/technicians")
    def tech_list():
        return jsonify(rows(conn.execute("SELECT * FROM technicians ORDER BY name")))

    @app.get("/api/technicians/<int:tid>/tasks")
    def tech_tasks(tid):
        svc.one(conn, "SELECT id FROM technicians WHERE id=?", (tid,), "Technician")
        mine = [svc.wo_view(conn, r["id"]) for r in conn.execute(
            "SELECT id FROM work_orders WHERE technician_id=? AND status='IN_PROGRESS' ORDER BY id", (tid,))]
        queue = [svc.wo_view(conn, r["id"]) for r in conn.execute(
            "SELECT id FROM work_orders WHERE status='OPEN' ORDER BY CASE priority WHEN 'AOG' THEN 0 WHEN 'HIGH' THEN 1"
            " WHEN 'NORMAL' THEN 2 ELSE 3 END, id")]
        return jsonify({"mine": mine, "openQueue": queue})

    # ---- ERP integration
    @app.get("/api/erp/outbox")
    def erp_outbox():
        return jsonify(rows(conn.execute("SELECT id, event, idem_key, status, erp_doc, attempts, last_error"
                                         " FROM erp_outbox ORDER BY id")))

    @app.post("/api/erp/sync")
    def erp_sync():
        return jsonify(erpmod.sync(conn, erp))

    @app.post("/api/erp/receipts")
    def erp_receipt():
        d = body()
        return jsonify(svc.receive_from_erp(conn, str(req(d, "partNo")), num(d, "qty", int, 0), d.get("poRef")))

    # ---- reporting
    @app.get("/api/reports/kpis")
    def kpis():
        k = svc.kpis(conn)
        k["recentMovements"] = rows(conn.execute(
            "SELECT p.part_no, m.delta, m.reason FROM stock_movements m JOIN parts p ON p.id = m.part_id"
            " ORDER BY m.id DESC LIMIT 8"))
        return jsonify(k)

    return app
