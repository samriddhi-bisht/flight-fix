#!/usr/bin/env bash
# One-command start for Linux / macOS: creates a virtual environment, installs Flask, starts FlightFix.
set -e
cd "$(dirname "$0")"
[ -d .venv ] || python3 -m venv .venv
. .venv/bin/activate
pip install -q -r requirements.txt
echo "FlightFix running at http://localhost:5000"
python run.py
