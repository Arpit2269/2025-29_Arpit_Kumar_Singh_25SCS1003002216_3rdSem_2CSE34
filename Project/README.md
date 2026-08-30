# NetSage AI

**Cisco Virtual Internship — Project 2: Applied AI + Network Troubleshooting**

NetSage AI is an evidence-driven troubleshooting assistant for Cisco-style
Packet Tracer/lab networks. It accepts a symptom, topology note, and
show-command output, then proposes a root cause, OSI layer, confidence,
literal evidence, next command, and fix steps.

> **Safety rule:** NetSage AI never applies a network fix automatically.
> Every diagnosis must pass validation and then be reviewed by a human as
> **Accepted, Edited, or Rejected**.

## Requirements covered

| Problem-statement requirement | Submission implementation |
|---|---|
| ≥30 cases | `cases.csv` contains **31** cases |
| Required fault coverage | VLAN 5, Gateway 4, DHCP 4, DNS 4, Routing 4, ACL 4, NAT 3, Wireless 3 |
| Evidence per case | Symptom, topology note, show output, expected fault, OSI layer, concept, severity |
| Structured AI prompts | `diagnose_prompt.md` with strict JSON schema + worked examples |
| Deterministic checker | `rule_checker.py` |
| Dashboard | Browser dashboard with category, severity, review outcomes, confidence, corrections |
| Human review | Review is API-gated until an AI diagnosis exists; notes are mandatory |
| Responsible AI | `responsible_ai_log.csv` contains **5 documented corrections** |
| Packet Tracer source | `NetSage_AI_Main.pkt` included |
| Demo history | `netsage_history.db` seeded with diagnoses, rule findings and reviews |

The official problem statement also asks the demo to show a broken case,
AI output, human review, fix, and verification. NetSage AI deliberately
stops before applying the fix; the human/operator performs the proposed
configuration change in Packet Tracer and then verifies it.

## Quick start

From the `netsage_ai` directory:

```bash
python -m pip install -r requirements.txt
python seed_data.py
python app.py
```

Open:

```text
http://127.0.0.1:5000
```

The seed command is idempotent for demo data: it clears previous diagnoses,
rule findings and reviews, then rebuilds the complete 31-case demonstration
state.

## What is included

```text
netsage_ai/
├── app.py
├── ai_engine.py
├── rule_checker.py
├── database.py
├── seed_data.py
├── validate_submission.py
├── cases.csv
├── diagnose_prompt.md
├── responsible_ai_log.csv
├── rule_checker_sample_output.txt
├── netsage_history.db
├── NetSage_AI_Main.pkt
├── requirements.txt
├── templates/index.html
└── static/
    ├── app.js
    └── style.css
```

## How the diagnosis works

The offline engine is intentionally deterministic so a grader can run it
without an API key or internet connection. It follows the structured prompt
contract and checks evidence patterns for:

- VLAN/access-port/trunk/native-VLAN faults
- Gateway/SVI/duplicate-IP/subnet-mask faults
- DHCP pool, helper-address and pool-network faults
- DNS server, stale-record and DNS-vs-ACL faults
- Routing, inactive-route and OSPF-area faults
- ACL deny, direction, implicit-deny and rule-order faults
- NAT overload, ACL coverage and static-port faults
- Wireless authentication, SSID broadcast and guest-isolation faults

`validate_diagnosis()` verifies that every required JSON field exists and that
each evidence item is a literal substring of the supplied show output.

## Deterministic rule checker

Run:

```bash
python rule_checker.py cases.csv
```

It independently checks duplicate IPs, invalid/mismatched masks, gateway
mismatch, down interfaces, missing VLANs, trunk allowed-VLAN omissions,
missing/inactive routes, ACL risks, DHCP problems, NAT problems, DNS problems,
and wireless problems.

The checker never changes configuration.

## Human review / Responsible AI

The API rejects review attempts when:

1. no AI diagnosis exists;
2. the review refers to an older diagnosis;
3. reviewer notes are empty;
4. an Edited review does not provide a corrected root cause.

The UI exposes Accepted, Edited and Rejected actions and clearly states that
no fix has been applied. After a review is recorded, an **Edit Review** button
lets a reviewer correct an accidental decision/note without creating a
misleading duplicate review. If AI Diagnosis is run again, the previous review
is treated as stale until the new diagnosis is reviewed.

Five seeded corrected cases are retained in `responsible_ai_log.csv`:
C004, C009, C013, C020 and C027. Each records the original AI diagnosis,
confidence, expected/corrected answer, and reviewer reasoning.

## Suggested 5–10 minute demo

1. Open Dashboard and show **31 cases / 8 categories**.
2. Open Case Browser and select **C018**.
3. Run **AI Diagnosis** and explain root cause, confidence, evidence,
   next command and proposed fix.
4. Run **Rule Checker** and compare its independent finding.
5. Record a human **Accepted** review with notes.
6. Open **C020** or **C027** to demonstrate a human correction/rejection.
7. Open Responsible AI Log and show all five corrections.
8. Open the Packet Tracer file, apply the proposed fix manually, and run the
   relevant verification command.
9. Return to the dashboard and show the review metrics.

## Offline note

The dashboard uses local HTML/CSS/JavaScript only; it does not depend on a
CDN or external AI service. Flask is the only runtime web framework required.
`netmiko` is retained in `requirements.txt` for Cisco/SSH compatibility with
the broader project work.
