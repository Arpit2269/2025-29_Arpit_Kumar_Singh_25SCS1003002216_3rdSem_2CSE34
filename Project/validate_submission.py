"""
Submission pre-flight validator.

Run from this directory:
    python validate_submission.py

It validates dataset coverage, diagnosis schema/evidence, deterministic
checker execution, responsible-AI log, source syntax, and database state.
"""
import csv
import os
import py_compile
import sqlite3

import database
import rule_checker
from ai_engine import diagnose, validate_diagnosis

ROOT = os.path.dirname(__file__)
REQUIRED = {"VLAN", "Gateway", "DHCP", "DNS", "Routing", "ACL", "NAT", "Wireless"}


def fail(msg):
    raise SystemExit("FAIL: " + msg)


def main():
    case_file = os.path.join(ROOT, "cases.csv")
    with open(case_file, newline="", encoding="utf-8") as f:
        cases = list(csv.DictReader(f))

    if len(cases) < 30:
        fail(f"Only {len(cases)} cases; at least 30 are required.")
    categories = {r["category"] for r in cases}
    missing = REQUIRED - categories
    if missing:
        fail(f"Missing required categories: {sorted(missing)}")

    required_columns = {
        "case_id","category","severity","symptom","topology_note",
        "show_output","expected_fault","osi_layer","concept"
    }
    if not required_columns.issubset(cases[0]):
        fail("cases.csv is missing required columns.")

    ids = [r["case_id"] for r in cases]
    if len(ids) != len(set(ids)):
        fail("Duplicate case_id found.")

    for case in cases:
        result = diagnose(case["category"], case["symptom"], case["topology_note"], case["show_output"])
        errors = validate_diagnosis(result, case["show_output"])
        if errors:
            fail(f"{case['case_id']} diagnosis validation: {errors}")
        rule_checker.check(case["show_output"], case["symptom"], case["topology_note"])

    log_file = os.path.join(ROOT, "responsible_ai_log.csv")
    with open(log_file, newline="", encoding="utf-8") as f:
        log = list(csv.DictReader(f))
    if len(log) < 5:
        fail(f"Responsible AI log has only {len(log)} corrected cases.")
    if not {"Edited", "Rejected"} & {r["decision"] for r in log}:
        fail("Responsible AI log has no Edited/Rejected case.")

    for fn in ("app.py", "ai_engine.py", "rule_checker.py", "database.py", "seed_data.py"):
        py_compile.compile(os.path.join(ROOT, fn), doraise=True)

    database.init_db()
    stats = database.dashboard_stats()
    if stats["total_cases"] < 30:
        fail("Database has fewer than 30 cases.")

    conn = sqlite3.connect(database.DB_PATH)
    diag_count = conn.execute("SELECT COUNT(DISTINCT case_id) FROM ai_diagnoses").fetchone()[0]
    review_count = conn.execute("SELECT COUNT(DISTINCT case_id) FROM human_reviews").fetchone()[0]
    conn.close()
    if diag_count < 30 or review_count < 30:
        fail(f"Seed state incomplete: diagnosed={diag_count}, reviewed={review_count}")

    print("PASS — NetSage AI submission pre-flight checks")
    print(f"  Cases: {len(cases)}")
    print(f"  Categories: {', '.join(sorted(categories))}")
    print(f"  Corrected Responsible-AI cases: {len(log)}")
    print(f"  Diagnosed in DB: {diag_count}")
    print(f"  Reviewed in DB: {review_count}")
    print("  Python syntax: OK")
    print("  Evidence validation: OK")
    print("  Deterministic checker: OK")


if __name__ == "__main__":
    main()
