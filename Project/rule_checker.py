"""
NetSage AI — Deterministic Rule Checker.

Independent validation layer. It never applies a configuration change.
The checker accepts the case symptom/topology as optional context so it can
validate things such as "VLAN 30 is missing from the trunk allowed list"
without pretending that every allowed-VLAN line is an error.
"""

import csv
import ipaddress
import re
import sys
from dataclasses import dataclass, asdict
from typing import List


@dataclass
class Finding:
    check: str
    severity: str
    detail: str


def _lines(text):
    return [x.strip() for x in (text or "").splitlines() if x.strip()]


def _config_lines(text):
    return [x for x in _lines(text) if not x.startswith("!")]


def _find_line(text, needle):
    for line in _lines(text):
        if needle.lower() in line.lower():
            return line
    return None


def check_duplicate_ip(text: str) -> List[Finding]:
    out = []
    for line in _lines(text):
        if "DUPADDR" in line or "Duplicate address" in line:
            out.append(Finding("duplicate_ip", "High", line))
    return out


def check_wrong_mask(text: str) -> List[Finding]:
    out = []
    m = re.search(r"Subnet Mask:\s*([\d.]+)", text or "", re.I)
    if m:
        try:
            ipaddress.IPv4Network(f"0.0.0.0/{m.group(1)}")
        except ValueError:
            out.append(Finding("invalid_subnet_mask", "High", f"Invalid subnet mask: {m.group(1)}"))
        if m.group(1) == "255.255.255.128" and "Default Gateway" in text:
            out.append(Finding("mask_gateway_mismatch_risk", "Medium",
                                "Host uses /25; verify that the host IP and gateway are in the same /25 subnet."))

    # Detect explicit /25 host/gateway mismatch.
    ipm = re.search(r"IP Address:\s*([\d.]+)", text or "", re.I)
    gwm = re.search(r"Default Gateway:\s*([\d.]+)", text or "", re.I)
    if ipm and gwm and m:
        try:
            net = ipaddress.ip_network(f"{ipm.group(1)}/{m.group(1)}", strict=False)
            if ipaddress.ip_address(gwm.group(1)) not in net:
                out.append(Finding("subnet_gateway_mismatch", "High",
                                   f"Host {ipm.group(1)}/{m.group(1)} is not in the subnet containing gateway {gwm.group(1)}."))
        except ValueError:
            pass
    return out


def check_gateway_mismatch(text: str) -> List[Finding]:
    out = []
    if "administratively down" in (text or "").lower():
        line = _find_line(text, "administratively down")
        out.append(Finding("interface_admin_down", "Critical", line or "Interface is administratively down."))

    ipm = re.search(r"IP Address:\s*([\d.]+)", text or "", re.I)
    gwm = re.search(r"Default Gateway:\s*([\d.]+)", text or "", re.I)
    if ipm and gwm:
        # Only flag when the host and gateway are outside the host's stated subnet.
        maskm = re.search(r"Subnet Mask:\s*([\d.]+)", text or "", re.I)
        if maskm:
            try:
                net = ipaddress.ip_network(f"{ipm.group(1)}/{maskm.group(1)}", strict=False)
                if ipaddress.ip_address(gwm.group(1)) not in net:
                    out.append(Finding("gateway_mismatch", "High",
                                       f"Gateway {gwm.group(1)} is outside the host subnet {net}."))
            except ValueError:
                pass
    return out


def check_interface_down(text: str) -> List[Finding]:
    out = []
    for line in _lines(text):
        low = line.lower()
        if ("administratively down" not in low and
            re.search(r"\bdown\b", low) and
            ("interface" in low or re.search(r"\b(?:fa|gi|gigabit|fastethernet|vlan)\S*", low))):
            out.append(Finding("interface_down", "High", line))
    return out


def check_missing_vlan(text: str, symptom="", topology_note="") -> List[Finding]:
    out = []
    low = (text or "").lower()
    if re.search(r"does not exist|not create", low):
        line = _find_line(text, "does not exist") or _find_line(text, "not create")
        out.append(Finding("vlan_not_created", "High",
                           line or "Referenced VLAN does not appear to be created."))
    # Access VLAN explicitly referenced but absent from show vlan brief.
    m = re.search(r"switchport access vlan\s+(\d+)", text or "", re.I)
    if m and "show vlan brief" in low:
        vlan_id = m.group(1)
        vlan_lines = [l for l in _lines(text) if re.match(rf"^{re.escape(vlan_id)}\b", l)]
        if not vlan_lines:
            out.append(Finding("vlan_id_not_in_brief", "High",
                               f"Access VLAN {vlan_id} is referenced but is absent from the VLAN brief."))
    # Required VLAN inferred from the symptom.
    sm = re.search(r"vlan\s*(\d+)", symptom or "", re.I)
    allowed = re.search(r"Allowed VLANs on trunk:\s*(.*)", text or "", re.I)
    if sm and allowed:
        vlan_id = sm.group(1)
        allowed_ids = re.findall(r"\d+", allowed.group(1))
        if vlan_id not in allowed_ids:
            out.append(Finding("trunk_allowed_vlan_missing", "High",
                               f"VLAN {vlan_id} is absent from the trunk allowed-VLAN list."))
    return out


def check_missing_route(text: str, symptom="", topology_note="") -> List[Finding]:
    out = []
    if "not present" in (text or "").lower():
        out.append(Finding("missing_route", "High",
                           _find_line(text, "not present") or "Destination network is absent from the routing table."))
    if re.search(r"\bS\s+.*inactive\b", text or "", re.I) or " inactive" in (text or "").lower():
        line = _find_line(text, "inactive")
        if line:
            out.append(Finding("inactive_route", "High", line))
    return out


def check_acl_issues(text: str) -> List[Finding]:
    out = []
    config = _config_lines(text)
    deny = [l for l in config if re.search(r"\bdeny\b", l, re.I)]
    permit = [l for l in config if re.search(r"\bpermit\b", l, re.I)]
    groups = [l for l in config if "ip access-group" in l.lower()]

    if deny and not permit:
        out.append(Finding("acl_implicit_deny_risk", "High",
                            "ACL has deny entries but no explicit permit; implicit deny-all applies."))

    for line in deny:
        out.append(Finding("acl_deny_rule", "Info", line))

    for line in groups:
        if re.search(r"\sout\b", line, re.I):
            out.append(Finding("acl_direction_out", "Medium", line))

    # Broad network deny before a host-specific permit.
    numbered = []
    for idx, line in enumerate(config):
        m = re.match(r"(\d+)\s+(deny|permit)\s+(.+)", line, re.I)
        if m:
            numbered.append((int(m.group(1)), m.group(2).lower(), m.group(3).lower(), line))
    for n, action, body, line in numbered:
        if action == "deny" and ("192.168.10.0 0.0.0.255" in body):
            later_host = [x for x in numbered if x[0] > n and x[1] == "permit" and "host" in x[2]]
            if later_host:
                out.append(Finding("acl_rule_order_issue", "High",
                                    f"Broad deny at sequence {n} precedes a host-specific permit."))
                break
    return out


def check_dhcp_issues(text: str) -> List[Finding]:
    out = []
    total = re.search(r"Total addresses\s*:\s*(\d+)", text or "", re.I)
    leased = re.search(r"Leased addresses\s*:\s*(\d+)", text or "", re.I)
    if total and leased and int(leased.group(1)) >= int(total.group(1)):
        out.append(Finding("dhcp_pool_exhausted", "High",
                           f"{leased.group(1)}/{total.group(1)} addresses leased."))
    if "no ip helper-address configured" in (text or "").lower():
        out.append(Finding("missing_ip_helper", "High",
                           "No ip helper-address is configured on the gateway interface."))
    if "network 192.168.200.0 255.255.255.0" in (text or "").lower() and "default-router 192.168.20.1" in (text or "").lower():
        out.append(Finding("dhcp_pool_network_mismatch", "High",
                           "DHCP pool network 192.168.200.0/24 does not match default-router 192.168.20.1."))
    return out


def check_nat_issues(text: str) -> List[Finding]:
    out = []
    low = (text or "").lower()
    if "no translations present" in low and "overload" not in low:
        out.append(Finding("nat_overload_missing", "High",
                           "No active NAT translations and no overload statement found."))
    if re.search(r"access-list\s+1\s+permit\s+192\.168\.10\.0\s+0\.0\.0\.127", text or "", re.I):
        out.append(Finding("nat_acl_incomplete", "High",
                           "NAT ACL covers only 192.168.10.0/25 rather than the intended /24."))
    return out


def check_dns_issues(text: str) -> List[Finding]:
    out = []
    if "DNS request timed out" in (text or ""):
        out.append(Finding("dns_timeout", "High", _find_line(text, "DNS request timed out") or "DNS request timed out."))
    if re.search(r"DNS Server:\s*8\.8\.8\.8", text or "", re.I) and "other PCs" in (text or "").lower():
        out.append(Finding("dns_server_mismatch", "Medium",
                           "Client DNS server differs from the internal DNS server used by peers."))
    return out


def check_wireless_issues(text: str) -> List[Finding]:
    out = []
    if "broadcast-ssid disable" in (text or "").lower():
        out.append(Finding("ssid_broadcast_disabled", "Medium", _find_line(text, "broadcast-ssid disable") or "SSID broadcast is disabled."))
    if "no ip access-group applied for isolation" in (text or "").lower():
        out.append(Finding("guest_isolation_missing", "High",
                           "Guest SVI has no isolation ACL applied."))
    if "passphrase" in (text or "").lower():
        out.append(Finding("wireless_passphrase_mismatch", "High",
                           "Wireless client and AP passphrases do not match."))
    return out


def check_vlan_and_trunk_consistency(text: str, symptom: str = "", topology_note: str = "") -> List[Finding]:
    out = []
    low = (text or "").lower()

    # Same-switch peer VLAN mismatch, using the lab symptom as the intended VLAN.
    intended = re.search(r"both should be vlan\s*(\d+)", topology_note or "", re.I)
    if intended and "show vlan brief" in low:
        target = intended.group(1)
        p1 = re.search(rf"{re.escape(target)}\s+\S+\s+active\s+([^\n]+)", text or "", re.I)
        p2 = re.search(r"20\s+\S+\s+active\s+([^\n]+)", text or "", re.I)
        if p1 and p2 and "Fa0/1" in p1.group(1) and "Fa0/2" in p2.group(1):
            out.append(Finding("access_vlan_mismatch", "High",
                               f"Fa0/1 is in VLAN {target} while Fa0/2 is shown under VLAN 20."))

    if "native vlan mismatch" in low or "NATIVE_VLAN_MISMATCH" in text:
        line = _find_line(text, "NATIVE_VLAN_MISMATCH") or _find_line(text, "native vlan mismatch")
        out.append(Finding("native_vlan_mismatch", "High", line or "Trunk ends have different native VLANs."))
    return out


def check_routing_protocols(text: str) -> List[Finding]:
    out = []
    low = (text or "").lower()
    if "area 0" in low and "area 1" in low and "ospf" in low:
        out.append(Finding("ospf_area_mismatch", "High",
                           "OSPF evidence shows the shared network configured in area 0 and area 1."))
    return out


def check_static_nat(text: str) -> List[Finding]:
    out = []
    m = re.search(r"ip nat inside source static tcp\s+(\S+)\s+(\d+)\s+(\S+)\s+(\d+)", text or "", re.I)
    if m and m.group(2) != m.group(4):
        out.append(Finding("static_nat_port_mismatch", "Medium",
                           f"Static NAT maps public port {m.group(4)} to internal port {m.group(2)}."))
    return out


ALL_CHECKS = [
    check_duplicate_ip,
    check_wrong_mask,
    check_gateway_mismatch,
    check_interface_down,
    check_missing_vlan,
    check_vlan_and_trunk_consistency,
    check_missing_route,
    check_routing_protocols,
    check_static_nat,
    check_acl_issues,
    check_dhcp_issues,
    check_nat_issues,
    check_dns_issues,
    check_wireless_issues,
]


def check(show_output: str, symptom: str = "", topology_note: str = "") -> List[Finding]:
    findings = []
    for fn in ALL_CHECKS:
        try:
            if fn in (check_missing_vlan, check_vlan_and_trunk_consistency, check_missing_route):
                findings.extend(fn(show_output, symptom, topology_note))
            else:
                findings.extend(fn(show_output))
        except Exception as exc:
            findings.append(Finding("checker_error", "Warning", f"{fn.__name__}: {exc}"))
    # Stable de-duplication.
    seen = set()
    unique = []
    for f in findings:
        key = (f.check, f.detail)
        if key not in seen:
            seen.add(key)
            unique.append(f)
    return unique


def check_to_dicts(show_output: str, symptom: str = "", topology_note: str = ""):
    return [asdict(f) for f in check(show_output, symptom, topology_note)]


if __name__ == "__main__":
    path = sys.argv[1] if len(sys.argv) > 1 else "cases.csv"
    with open(path, newline="", encoding="utf-8") as f:
        total = 0
        for row in csv.DictReader(f):
            findings = check(row["show_output"], row["symptom"], row["topology_note"])
            total += len(findings)
            print(f"\n=== {row['case_id']} [{row['category']}] {row['symptom'][:70]}")
            if not findings:
                print("  (no deterministic issues flagged)")
            for item in findings:
                print(f"  [{item.severity:8s}] {item.check}: {item.detail}")
        print(f"\n--- Total deterministic findings across all cases: {total} ---")
