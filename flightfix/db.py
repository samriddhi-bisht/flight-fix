import sqlite3

SCHEMA = """
CREATE TABLE IF NOT EXISTS aircraft(
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    tail TEXT NOT NULL UNIQUE,
    model TEXT NOT NULL,
    flight_hours REAL NOT NULL DEFAULT 0 CHECK(flight_hours >= 0),
    cycles INTEGER NOT NULL DEFAULT 0 CHECK(cycles >= 0),
    status TEXT NOT NULL DEFAULT 'SERVICEABLE');
CREATE TABLE IF NOT EXISTS task_templates(
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    code TEXT NOT NULL UNIQUE,
    title TEXT NOT NULL,
    interval_hours REAL, interval_days INTEGER, interval_cycles INTEGER,
    est_hours REAL NOT NULL DEFAULT 1,
    CHECK(interval_hours IS NOT NULL OR interval_days IS NOT NULL OR interval_cycles IS NOT NULL));
CREATE TABLE IF NOT EXISTS aircraft_tasks(
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    aircraft_id INTEGER NOT NULL REFERENCES aircraft(id),
    template_id INTEGER NOT NULL REFERENCES task_templates(id),
    last_done_date TEXT NOT NULL,
    last_done_hours REAL NOT NULL,
    last_done_cycles INTEGER NOT NULL,
    UNIQUE(aircraft_id, template_id));
CREATE TABLE IF NOT EXISTS parts(
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    part_no TEXT NOT NULL UNIQUE,
    barcode TEXT UNIQUE,
    name TEXT NOT NULL,
    category TEXT,
    unit_cost REAL NOT NULL CHECK(unit_cost >= 0),
    qty INTEGER NOT NULL DEFAULT 0 CHECK(qty >= 0),
    reorder_level INTEGER NOT NULL DEFAULT 0,
    supplier TEXT,
    lead_days INTEGER NOT NULL DEFAULT 7);
CREATE TABLE IF NOT EXISTS technicians(
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL,
    licence_no TEXT NOT NULL UNIQUE,
    skill TEXT);
CREATE TABLE IF NOT EXISTS work_orders(
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    wo_number TEXT NOT NULL UNIQUE,
    aircraft_id INTEGER NOT NULL REFERENCES aircraft(id),
    template_id INTEGER REFERENCES task_templates(id),
    title TEXT NOT NULL,
    kind TEXT NOT NULL CHECK(kind IN ('SCHEDULED','DEFECT')),
    priority TEXT NOT NULL DEFAULT 'NORMAL',
    status TEXT NOT NULL DEFAULT 'OPEN'
        CHECK(status IN ('OPEN','IN_PROGRESS','COMPLETED','CANCELLED')),
    technician_id INTEGER REFERENCES technicians(id),
    created_at TEXT NOT NULL, started_at TEXT, completed_at TEXT,
    labour_hours REAL NOT NULL DEFAULT 0);
CREATE TABLE IF NOT EXISTS part_issues(
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    work_order_id INTEGER NOT NULL REFERENCES work_orders(id),
    part_id INTEGER NOT NULL REFERENCES parts(id),
    qty INTEGER NOT NULL CHECK(qty > 0),
    unit_cost REAL NOT NULL,
    issued_at TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS stock_movements(
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    part_id INTEGER NOT NULL REFERENCES parts(id),
    delta INTEGER NOT NULL,
    reason TEXT NOT NULL,
    created_at TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS erp_outbox(
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    event TEXT NOT NULL,
    idem_key TEXT NOT NULL UNIQUE,
    payload TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'PENDING',
    erp_doc TEXT,
    attempts INTEGER NOT NULL DEFAULT 0,
    last_error TEXT,
    created_at TEXT NOT NULL,
    sent_at TEXT);
"""


def connect(path):
    conn = sqlite3.connect(path, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    conn.executescript(SCHEMA)
    return conn
