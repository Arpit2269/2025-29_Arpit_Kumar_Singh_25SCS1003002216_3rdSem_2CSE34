"""
Seed the complete offline demo state.

This is intentionally idempotent: it clears only NetSage demo diagnosis/review
tables, preserves the case dataset, re-runs all 31 diagnoses and the rule
checker, then recreates five documented human corrections.
"""

import csv
import os
import database
import rule_checker
from ai_engine import diagnose, validate_diagnosis


CORRECTIONS = {
    "C004": (
        "Edited",
        "AI identified the native VLAN mismatch, but the reviewer clarified that both trunk ends must use the same native VLAN.",
        "Standardize the native VLAN on both SW1 Gi0/2 and SW2 Gi0/2 to VLAN 1."
    ),
    "C009": (
        "Edited",
        "Reviewer verified the /25 boundary: host 192.168.10.140 is in the second /25 while gateway 192.168.10.1 is in the first.",
        "Correct the host subnet mask/addressing so the host and gateway are in the intended subnet."
    ),
    "C013": (
        "Edited",
        "AI detected a single-address exclusion, but the reviewer added the exact reserved range required by the topology.",
        "Exclude 192.168.10.1 through 192.168.10.10 from the DHCP pool."
    ),
    "C020": (
        "Edited",
        "AI found the OSPF area mismatch; reviewer clarified that both routers on the shared link must agree on the same area.",
        "Configure both R1 and R2 to use the same OSPF area on the shared link."
    ),
    "C027": (
        "Rejected",
        "AI correctly noticed the /25 NAT ACL, but the reviewer rejected the first-pass diagnosis because it did not explicitly require a complete NAT configuration verification before any change.",
        "Expand the NAT ACL to cover the intended internal subnet and verify the complete NAT configuration before approval."
    ),
}


def main():
    database.init_db()
    database.reset_demo_data()
    cases = database.list_cases()
    if len(cases) < 30:
        raise SystemExit(f"Dataset validation failed: only {len(cases)} cases found.")

    for case in cases:
        result = diagnose(
            case["category"], case["symptom"],
            case["topology_note"], case["show_output"]
        )
        errors = validate_diagnosis(result, case["show_output"])
        if errors:
            raise SystemExit(f"{case['case_id']} diagnosis validation failed: {errors}")

        diag_id = database.save_ai_diagnosis(case["case_id"], result)
        findings = rule_checker.check_to_dicts(
            case["show_output"], case["symptom"], case["topology_note"]
        )
        database.save_rule_findings(case["case_id"], findings)

        if case["case_id"] in CORRECTIONS:
            decision, notes, corrected = CORRECTIONS[case["case_id"]]
        else:
            decision = "Accepted"
            notes = "Reviewer compared the diagnosis with the known expected fault and approved it."
            corrected = None

        database.save_review(
            case["case_id"], diag_id, decision, notes, corrected
        )

    log_rows = database.responsible_ai_cases()
    with open(os.path.join(database.BASE_DIR, "responsible_ai_log.csv"),
              "w", newline="", encoding="utf-8") as f:
        fields = [
            "case_id", "category", "decision", "ai_root_cause",
            "ai_confidence", "expected_fault", "corrected_root_cause",
            "reviewer_notes"
        ]
        writer = csv.DictWriter(f, fieldnames=fields)
        writer.writeheader()
        for row in log_rows:
            writer.writerow({k: row.get(k, "") for k in fields})

    print(f"Seed complete: {len(cases)} cases diagnosed and reviewed.")
    print(f"Responsible AI corrections: {len(log_rows)}")
    print(database.dashboard_stats())


if __name__ == "__main__":
    main()
