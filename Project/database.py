"""
NetSage AI — SQLite data layer.
"""

import csv
import json
import os
import sqlite3
from datetime import datetime, timezone

BASE_DIR = os.path.dirname(__file__)
DB_PATH = os.path.join(BASE_DIR, "netsage_history.db")
CASES_CSV = os.path.join(BASE_DIR, "cases.csv")


def now_iso():
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def get_conn():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


def init_db():
    conn = get_conn()
    conn.executescript("""
        CREATE TABLE IF NOT EXISTS cases (
            case_id TEXT PRIMARY KEY,
            category TEXT NOT NULL,
            severity TEXT NOT NULL,
            symptom TEXT NOT NULL,
            topology_note TEXT NOT NULL,
            show_output TEXT NOT NULL,
            expected_fault TEXT NOT NULL,
            osi_layer TEXT NOT NULL,
            concept TEXT NOT NULL
        );

        CREATE TABLE IF NOT EXISTS ai_diagnoses (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            case_id TEXT NOT NULL,
            timestamp TEXT NOT NULL,
            root_cause TEXT NOT NULL,
            osi_layer TEXT NOT NULL,
            confidence INTEGER NOT NULL,
            evidence TEXT NOT NULL,
            next_command TEXT NOT NULL,
            fix_steps TEXT NOT NULL,
            FOREIGN KEY(case_id) REFERENCES cases(case_id)
        );

        CREATE TABLE IF NOT EXISTS human_reviews (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            case_id TEXT NOT NULL,
            diagnosis_id INTEGER NOT NULL,
            timestamp TEXT NOT NULL,
            decision TEXT NOT NULL CHECK(decision IN ('Accepted','Edited','Rejected')),
            reviewer_notes TEXT NOT NULL,
            corrected_root_cause TEXT,
            FOREIGN KEY(case_id) REFERENCES cases(case_id),
            FOREIGN KEY(diagnosis_id) REFERENCES ai_diagnoses(id)
        );

        CREATE TABLE IF NOT EXISTS rule_findings (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            case_id TEXT NOT NULL,
            check_name TEXT NOT NULL,
            severity TEXT NOT NULL,
            detail TEXT NOT NULL,
            timestamp TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
        );

        CREATE INDEX IF NOT EXISTS idx_diag_case ON ai_diagnoses(case_id, id DESC);
        CREATE INDEX IF NOT EXISTS idx_review_case ON human_reviews(case_id, id DESC);
        CREATE INDEX IF NOT EXISTS idx_rule_case ON rule_findings(case_id);
    """)

    count = conn.execute("SELECT COUNT(*) AS c FROM cases").fetchone()["c"]
    if count == 0 and os.path.exists(CASES_CSV):
        with open(CASES_CSV, newline="", encoding="utf-8") as f:
            rows = list(csv.DictReader(f))
        conn.executemany(
            """INSERT INTO cases
            (case_id, category, severity, symptom, topology_note, show_output,
             expected_fault, osi_layer, concept)
            VALUES (?,?,?,?,?,?,?,?,?)""",
            [(
                r["case_id"], r["category"], r["severity"], r["symptom"],
                r["topology_note"], r["show_output"], r["expected_fault"],
                r["osi_layer"], r["concept"]
            ) for r in rows]
        )
    # Lightweight migration for an older submission database.
    columns = {row["name"] for row in conn.execute("PRAGMA table_info(rule_findings)").fetchall()}
    if "timestamp" not in columns:
        conn.execute("ALTER TABLE rule_findings ADD COLUMN timestamp TEXT")
    conn.commit()
    conn.close()


def reset_demo_data():
    conn = get_conn()
    conn.execute("DELETE FROM human_reviews")
    conn.execute("DELETE FROM rule_findings")
    conn.execute("DELETE FROM ai_diagnoses")
    conn.commit()
    conn.close()


def list_cases():
    conn = get_conn()
    rows = conn.execute("SELECT * FROM cases ORDER BY case_id").fetchall()
    conn.close()
    return [dict(r) for r in rows]


def get_case(case_id):
    conn = get_conn()
    row = conn.execute("SELECT * FROM cases WHERE case_id=?", (case_id,)).fetchone()
    conn.close()
    return dict(row) if row else None


def save_ai_diagnosis(case_id, diagnosis):
    conn = get_conn()
    cur = conn.execute(
        """INSERT INTO ai_diagnoses
        (case_id,timestamp,root_cause,osi_layer,confidence,evidence,next_command,fix_steps)
        VALUES (?,?,?,?,?,?,?,?)""",
        (
            case_id, now_iso(), diagnosis["root_cause"], diagnosis["osi_layer"],
            int(diagnosis["confidence"]), json.dumps(diagnosis["evidence"]),
            diagnosis["next_command"], json.dumps(diagnosis["fix_steps"])
        )
    )
    conn.commit()
    ident = cur.lastrowid
    conn.close()
    return ident


def latest_diagnosis(case_id):
    conn = get_conn()
    row = conn.execute(
        "SELECT * FROM ai_diagnoses WHERE case_id=? ORDER BY id DESC LIMIT 1",
        (case_id,)
    ).fetchone()
    conn.close()
    if not row:
        return None
    d = dict(row)
    d["evidence"] = json.loads(d["evidence"] or "[]")
    d["fix_steps"] = json.loads(d["fix_steps"] or "[]")
    return d


def save_review(case_id, diagnosis_id, decision, notes, corrected_root_cause=None):
    conn = get_conn()
    exists = conn.execute(
        "SELECT id FROM ai_diagnoses WHERE id=? AND case_id=?",
        (diagnosis_id, case_id)
    ).fetchone()
    if not exists:
        conn.close()
        raise ValueError("A valid AI diagnosis is required before human review.")
    conn.execute(
        """INSERT INTO human_reviews
        (case_id,diagnosis_id,timestamp,decision,reviewer_notes,corrected_root_cause)
        VALUES (?,?,?,?,?,?)""",
        (case_id, diagnosis_id, now_iso(), decision, notes, corrected_root_cause)
    )
    conn.commit()
    conn.close()


def latest_review(case_id):
    """Return the review only when it belongs to the latest AI diagnosis.

    Re-running diagnosis creates a new diagnosis version. Any older review is
    therefore stale and must not be displayed as approval for the new result.
    """
    conn = get_conn()
    row = conn.execute(
        """SELECT hr.*
        FROM human_reviews hr
        JOIN ai_diagnoses ad ON ad.id = hr.diagnosis_id AND ad.case_id = hr.case_id
        WHERE hr.case_id=?
          AND hr.diagnosis_id=(SELECT MAX(id) FROM ai_diagnoses WHERE case_id=?)
        ORDER BY hr.id DESC LIMIT 1""",
        (case_id, case_id)
    ).fetchone()
    conn.close()
    return dict(row) if row else None


def update_review(case_id, review_id, diagnosis_id, decision, notes, corrected_root_cause=None):
    """Edit the current review without creating a misleading second review."""
    conn = get_conn()
    row = conn.execute(
        """SELECT hr.id
        FROM human_reviews hr
        WHERE hr.id=? AND hr.case_id=? AND hr.diagnosis_id=?
          AND hr.diagnosis_id=(SELECT MAX(id) FROM ai_diagnoses WHERE case_id=?)""",
        (review_id, case_id, diagnosis_id, case_id)
    ).fetchone()
    if not row:
        conn.close()
        raise ValueError("Review is no longer current. Re-run AI diagnosis and review the latest result.")
    conn.execute(
        """UPDATE human_reviews
        SET timestamp=?, decision=?, reviewer_notes=?, corrected_root_cause=?
        WHERE id=?""",
        (now_iso(), decision, notes, corrected_root_cause, review_id)
    )
    conn.commit()
    conn.close()


def save_rule_findings(case_id, findings):
    conn = get_conn()
    conn.execute("DELETE FROM rule_findings WHERE case_id=?", (case_id,))
    conn.executemany(
        """INSERT INTO rule_findings
        (case_id,check_name,severity,detail,timestamp) VALUES (?,?,?,?,?)""",
        [(case_id, f["check"], f["severity"], f["detail"], now_iso()) for f in findings]
    )
    conn.commit()
    conn.close()


def get_rule_findings(case_id):
    conn = get_conn()
    rows = conn.execute(
        "SELECT check_name, severity, detail FROM rule_findings WHERE case_id=? ORDER BY id",
        (case_id,)
    ).fetchall()
    conn.close()
    return [dict(r) for r in rows]


def dashboard_stats():
    conn = get_conn()
    total_cases = conn.execute("SELECT COUNT(*) AS c FROM cases").fetchone()["c"]
    diagnosed = conn.execute(
        "SELECT COUNT(DISTINCT case_id) AS c FROM ai_diagnoses"
    ).fetchone()["c"]

    by_category = conn.execute(
        "SELECT category, COUNT(*) AS c FROM cases GROUP BY category ORDER BY c DESC, category"
    ).fetchall()
    by_severity = conn.execute(
        "SELECT severity, COUNT(*) AS c FROM cases GROUP BY severity ORDER BY c DESC, severity"
    ).fetchall()

    latest_review_rows = conn.execute("""
        SELECT hr.*
        FROM human_reviews hr
        JOIN (
            SELECT case_id, MAX(id) AS max_id
            FROM ai_diagnoses GROUP BY case_id
        ) d ON d.case_id = hr.case_id AND d.max_id = hr.diagnosis_id
        JOIN (
            SELECT case_id, MAX(id) AS max_id
            FROM human_reviews GROUP BY case_id
        ) r ON r.max_id = hr.id
    """).fetchall()
    review_counts = {}
    for r in latest_review_rows:
        review_counts[r["decision"]] = review_counts.get(r["decision"], 0) + 1
    total_reviewed = sum(review_counts.values())
    accepted = review_counts.get("Accepted", 0)

    latest_diag_rows = conn.execute("""
        SELECT ad.confidence
        FROM ai_diagnoses ad
        JOIN (
            SELECT case_id, MAX(id) AS max_id
            FROM ai_diagnoses GROUP BY case_id
        ) x ON x.max_id = ad.id
    """).fetchall()
    confidences = [r["confidence"] for r in latest_diag_rows]
    avg_confidence = round(sum(confidences) / len(confidences), 1) if confidences else 0.0

    corrected = conn.execute("""
        SELECT COUNT(*) AS c
        FROM human_reviews hr
        JOIN (
            SELECT case_id, MAX(id) AS max_id
            FROM human_reviews GROUP BY case_id
        ) r ON r.max_id = hr.id
        JOIN (
            SELECT case_id, MAX(id) AS max_id
            FROM ai_diagnoses GROUP BY case_id
        ) d ON d.case_id = hr.case_id AND d.max_id = hr.diagnosis_id
        WHERE hr.decision IN ('Edited','Rejected')
    """).fetchone()["c"]

    conn.close()
    return {
        "total_cases": total_cases,
        "total_diagnosed": diagnosed,
        "by_category": [dict(r) for r in by_category],
        "by_severity": [dict(r) for r in by_severity],
        "review_breakdown": [{"decision": k, "c": v} for k, v in review_counts.items()],
        "total_reviewed": total_reviewed,
        "agreement_rate": round(100 * accepted / total_reviewed, 1) if total_reviewed else 0.0,
        "avg_confidence": avg_confidence,
        "corrected_cases": corrected,
        "unreviewed": max(0, total_cases - total_reviewed),
    }


def responsible_ai_cases():
    conn = get_conn()
    rows = conn.execute("""
        SELECT hr.case_id, c.category, c.expected_fault,
               hr.decision, hr.timestamp, hr.reviewer_notes, hr.corrected_root_cause,
               ad.root_cause AS ai_root_cause, ad.confidence AS ai_confidence
        FROM human_reviews hr
        JOIN cases c ON c.case_id = hr.case_id
        LEFT JOIN ai_diagnoses ad ON ad.id = hr.diagnosis_id
        WHERE hr.decision IN ('Edited','Rejected')
        ORDER BY hr.id DESC
    """).fetchall()
    conn.close()
    return [dict(r) for r in rows]
