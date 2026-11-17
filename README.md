# FlightFix

Aircraft maintenance efficiency: a lightweight MRO (maintenance, repair and overhaul) platform with
maintenance planning, spare-parts inventory, ERP integration and a mobile technician screen.

Built with Python 3.12, Flask 3, SQLite and a zero-build vanilla JavaScript interface.
HCLTech Career Shaper Programme project by Samriddhi Bisht (Roll 2300320230049), ABES Engineering College.

## What it does

- **Planning engine.** Each task has hour, cycle and calendar intervals. The engine finds whichever limit
  comes first and marks every task OK, DUE SOON or OVERDUE. One call raises prioritised work orders without duplicates.
- **Work-order lifecycle.** OPEN, IN PROGRESS, COMPLETED or CANCELLED, with state rules enforced on the server.
- **Stock integrity.** Every part movement goes through one function that refuses negative stock and logs a ledger row.
  A multi-line issue applies fully or rolls back entirely.
- **ERP outbox.** Sign-off writes the cost posting in the same commit. Failures are kept and retried, and an
  idempotency key means a retry never creates a second ERP document. Goods receipts flow back in as stock.
- **Technician screen.** Mobile-first: start jobs, scan a part number or barcode, issue parts, sign off.

## Run it

```bash
pip install -r requirements.txt
python run.py                      # http://localhost:5000, data kept in ./data/flightfix.db
python -m unittest tests.test_flightfix -v   # the 12 acceptance tests
```

The database seeds itself on first start with 5 aircraft, 6 task templates, 12 parts and 4 technicians.

Optional environment variables:

```bash
FLIGHTFIX_TODAY=2026-11-01 python run.py                         # pin "today" for repeatable demos
FLIGHTFIX_ERP_URL=https://erp.example/api/postings python run.py # use a real ERP gateway (HttpERP)
```

## Layout

```
run.py                     entry point
flightfix/app.py           Flask API, 21 JSON endpoints, error handlers (400 / 404 / 409)
flightfix/services.py      planning engine, work-order lifecycle, stock gateway, KPIs
flightfix/erp.py           outbox, MockERP, HttpERP
flightfix/db.py            SQLite schema (9 tables)
flightfix/seed.py          demo data
flightfix/static/          index.html, app.css, app.js
tests/test_flightfix.py    TC1 to TC12
```

## API

| Method | Route | Purpose |
|---|---|---|
| GET / POST | `/api/aircraft` | list or register an aircraft |
| GET | `/api/plan` | every task with due status, most urgent first |
| POST | `/api/plan/generate` | raise work orders for overdue and due-soon tasks |
| GET / POST | `/api/work-orders` | list or raise a defect |
| GET | `/api/work-orders/{id}` | one work order |
| POST | `/api/work-orders/{id}/start` | assign a technician and start |
| POST | `/api/work-orders/{id}/issue-part` | issue parts, all or none |
| POST | `/api/work-orders/{id}/complete` | sign off, reset counters, queue ERP posting |
| POST | `/api/work-orders/{id}/cancel` | cancel an open or in-progress job |
| GET / POST | `/api/parts` | list (with `?q=`) or add a part |
| POST | `/api/parts/{id}/adjust` | add or remove units |
| GET | `/api/parts/lookup/{code}` | resolve a part number or barcode |
| GET | `/api/technicians` | list technicians |
| GET | `/api/technicians/{id}/tasks` | my in-progress jobs and the open queue |
| GET | `/api/erp/outbox` | outbox rows |
| POST | `/api/erp/sync` | push pending rows to the ERP connector |
| POST | `/api/erp/receipts` | inbound goods receipt |
| GET | `/api/reports/kpis` | availability, overdue, inventory value, reorder alerts, ERP queue |

## Note

FlightFix is a learning project. It is not certified maintenance-records software and must not be used for real airworthiness decisions.
