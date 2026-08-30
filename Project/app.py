"""
NetSage AI — Flask application.

Run:
    pip install -r requirements.txt
    python app.py
Open:
    http://127.0.0.1:5000
"""

from flask import Flask, jsonify, render_template, request

import database
import rule_checker
from ai_engine import diagnose, validate_diagnosis

app = Flask(__name__)
database.init_db()


@app.route("/")
def index():
    return render_template("index.html")


@app.route("/api/cases")
def api_cases():
    cases = database.list_cases()
    for case in cases:
        case["latest_diagnosis"] = database.latest_diagnosis(case["case_id"])
        case["latest_review"] = database.latest_review(case["case_id"])
    return jsonify(cases)


@app.route("/api/case/<case_id>")
def api_case(case_id):
    case = database.get_case(case_id)
    if not case:
        return jsonify({"error": "case not found"}), 404
    case["latest_diagnosis"] = database.latest_diagnosis(case_id)
    case["latest_review"] = database.latest_review(case_id)
    case["rule_findings"] = database.get_rule_findings(case_id)
    return jsonify(case)


@app.route("/api/diagnose/<case_id>", methods=["POST"])
def api_diagnose(case_id):
    case = database.get_case(case_id)
    if not case:
        return jsonify({"error": "case not found"}), 404

    result = diagnose(
        case["category"], case["symptom"],
        case["topology_note"], case["show_output"]
    )
    errors = validate_diagnosis(result, case["show_output"])
    if errors:
        return jsonify({
            "error": "Diagnosis failed safety validation.",
            "validation_errors": errors
        }), 500

    diag_id = database.save_ai_diagnosis(case_id, result)
    findings = rule_checker.check_to_dicts(
        case["show_output"], case["symptom"], case["topology_note"]
    )
    database.save_rule_findings(case_id, findings)

    result["diagnosis_id"] = diag_id
    result["rule_findings"] = findings
    return jsonify(result)


@app.route("/api/rulecheck/<case_id>", methods=["POST"])
def api_rulecheck(case_id):
    case = database.get_case(case_id)
    if not case:
        return jsonify({"error": "case not found"}), 404
    findings = rule_checker.check_to_dicts(
        case["show_output"], case["symptom"], case["topology_note"]
    )
    database.save_rule_findings(case_id, findings)
    return jsonify(findings)


@app.route("/api/review/<case_id>", methods=["POST"])
def api_review(case_id):
    case = database.get_case(case_id)
    if not case:
        return jsonify({"error": "case not found"}), 404

    body = request.get_json(silent=True) or {}
    decision = body.get("decision")
    notes = (body.get("notes") or "").strip()
    corrected = (body.get("corrected_root_cause") or "").strip() or None
    diagnosis_id = body.get("diagnosis_id")

    if decision not in ("Accepted", "Edited", "Rejected"):
        return jsonify({"error": "decision must be Accepted, Edited, or Rejected"}), 400

    latest = database.latest_diagnosis(case_id)
    if not latest:
        return jsonify({
            "error": "Human review is gated: run AI Diagnosis first."
        }), 409

    if diagnosis_id is None:
        diagnosis_id = latest["id"]
    try:
        diagnosis_id = int(diagnosis_id)
    except (TypeError, ValueError):
        return jsonify({"error": "Invalid diagnosis_id"}), 400

    if diagnosis_id != latest["id"]:
        return jsonify({
            "error": "Review must be attached to the latest diagnosis. Re-run diagnosis if needed."
        }), 409

    if not notes:
        return jsonify({"error": "Reviewer notes are required."}), 400

    if decision == "Edited" and not corrected:
        return jsonify({
            "error": "Edited review requires corrected_root_cause."
        }), 400

    if decision == "Accepted":
        corrected = None

    review_id = body.get("review_id")
    try:
        if review_id is not None:
            review_id = int(review_id)
            database.update_review(case_id, review_id, diagnosis_id, decision, notes, corrected)
            message = "Human review updated. No fix was applied by NetSage AI."
        else:
            database.save_review(case_id, diagnosis_id, decision, notes, corrected)
            message = "Human review recorded. No fix was applied by NetSage AI."
    except (TypeError, ValueError) as exc:
        return jsonify({"error": str(exc)}), 409

    return jsonify({"status": "ok", "message": message})


@app.route("/api/dashboard")
def api_dashboard():
    return jsonify(database.dashboard_stats())


@app.route("/api/responsible-log")
def api_responsible_log():
    return jsonify(database.responsible_ai_cases())


@app.route("/api/health")
def api_health():
    stats = database.dashboard_stats()
    return jsonify({
        "status": "ok",
        "service": "NetSage AI",
        "cases": stats["total_cases"],
        "diagnosed": stats["total_diagnosed"],
        "human_review_required": True,
        "version": "2.0-submission"
    })


if __name__ == "__main__":
    app.run(debug=False, host="127.0.0.1", port=5000)
