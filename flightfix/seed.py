"""Loads a demo airline maintenance base the first time the app starts."""
import random
from datetime import timedelta

from . import services as svc

FLEET = [("VT-FFA", "ATR 72-600", 18420.5, 21300), ("VT-FFB", "ATR 72-600", 12110.0, 14800),
         ("VT-FFC", "Airbus A320neo", 9650.2, 5120), ("VT-FFD", "Airbus A320neo", 7310.8, 3990),
         ("VT-FFE", "Boeing 737-800", 31200.4, 17650)]
# code, title, interval hours, interval days, interval cycles, estimated labour hours
TEMPLATES = [("A-CHK", "A-Check line inspection", 600, 120, None, 24),
             ("C-CHK", "C-Check heavy inspection", None, 730, None, 300),
             ("LG-INSP", "Landing gear inspection", None, None, 1500, 16),
             ("ENG-BSI", "Engine borescope inspection", 1500, None, None, 12),
             ("CAB-PRS", "Cabin pressure leak check", None, 90, None, 6),
             ("O2-CHK", "Oxygen system check", None, 180, None, 4)]
# part no, name, category, unit cost INR, opening qty, reorder level, supplier, lead days
PARTS = [("FF-P-1001", "Main wheel assembly", "Landing gear", 185000, 6, 4, "Aerotech Components", 21),
         ("FF-P-1002", "Brake disc stack", "Landing gear", 92000, 10, 6, "Aerotech Components", 18),
         ("FF-P-2001", "Hydraulic pump seal kit", "Hydraulics", 12500, 3, 8, "SkyBridge Aerospace", 12),
         ("FF-P-2002", "Hydraulic fluid 20 L", "Hydraulics", 14800, 12, 6, "SkyBridge Aerospace", 9),
         ("FF-P-3001", "Engine oil filter", "Engine", 6200, 18, 10, "Ardent Aviation Supply", 7),
         ("FF-P-3002", "Fuel nozzle", "Engine", 48000, 0, 4, "Ardent Aviation Supply", 25),
         ("FF-P-3003", "Igniter plug", "Engine", 9800, 14, 6, "Ardent Aviation Supply", 7),
         ("FF-P-4001", "Crew oxygen bottle", "Cabin", 27000, 5, 3, "SkyBridge Aerospace", 14),
         ("FF-P-4002", "Outflow valve gasket", "Cabin", 4300, 20, 8, "SkyBridge Aerospace", 6),
         ("FF-P-5001", "Avionics cooling fan", "Avionics", 31500, 2, 3, "Aerotech Components", 15),
         ("FF-P-5002", "Pitot tube heater", "Avionics", 22000, 7, 3, "Aerotech Components", 15),
         ("FF-P-6001", "Torque-sealed fastener kit", "Consumables", 1800, 120, 50, "Ardent Aviation Supply", 4)]
# make the demo interesting: push two tasks close to their limit
NEAR_LIMIT = {("VT-FFB", "ENG-BSI"): 0.96, ("VT-FFD", "A-CHK"): 0.93}
TECHS = [("Ravi Menon", "AME-B1-20418", "Engines and airframe"), ("Priya Nair", "AME-B2-31772", "Avionics"),
         ("Imran Qureshi", "AME-B1-20955", "Landing gear and hydraulics"), ("Divya Rao", "AME-B1-33410", "Cabin and structures")]


def seed(conn):
    if conn.execute("SELECT COUNT(*) FROM aircraft").fetchone()[0]:
        return
    rnd = random.Random(11)
    with conn:
        for code, title, h, d, c, est in TEMPLATES:
            conn.execute("INSERT INTO task_templates(code, title, interval_hours, interval_days, interval_cycles,"
                         " est_hours) VALUES(?,?,?,?,?,?)", (code, title, h, d, c, est))
        for tail, model, hours, cycles in FLEET:
            aid = conn.execute("INSERT INTO aircraft(tail, model, flight_hours, cycles) VALUES(?,?,?,?)",
                               (tail, model, hours, cycles)).lastrowid
            for t in conn.execute("SELECT * FROM task_templates").fetchall():
                f = NEAR_LIMIT.get((tail, t["code"]), rnd.uniform(0.35, 1.08))  # share of interval used
                conn.execute(
                    "INSERT INTO aircraft_tasks(aircraft_id, template_id, last_done_date, last_done_hours,"
                    " last_done_cycles) VALUES(?,?,?,?,?)",
                    (aid, t["id"], (svc.today() - timedelta(days=round((t["interval_days"] or 365) * f))).isoformat(),
                     round(hours - (t["interval_hours"] or 0) * f, 1), int(cycles - (t["interval_cycles"] or 0) * f)))
        for i, (no, name, cat, cost, qty, reorder, sup, lead) in enumerate(PARTS, 1):
            pid = conn.execute("INSERT INTO parts(part_no, barcode, name, category, unit_cost, reorder_level, supplier,"
                               " lead_days) VALUES(?,?,?,?,?,?,?,?)",
                               (no, "89012340%04d" % i, name, cat, cost, reorder, sup, lead)).lastrowid
            if qty:
                svc._adjust(conn, pid, qty, "Opening stock")
        for name, lic, skill in TECHS:
            conn.execute("INSERT INTO technicians(name, licence_no, skill) VALUES(?,?,?)", (name, lic, skill))
