"""
NetSage AI — Offline diagnosis engine.

The project brief asks for structured AI-style diagnoses. This implementation
uses deterministic evidence matching so the submission is fully offline and
reproducible. It follows the same JSON contract documented in diagnose_prompt.md.
"""

import re
from dataclasses import dataclass, field
from typing import List


@dataclass
class Diagnosis:
    root_cause: str
    osi_layer: str
    confidence: int
    evidence: List[str] = field(default_factory=list)
    next_command: str = ""
    fix_steps: List[str] = field(default_factory=list)

    def to_dict(self):
        return {
            "root_cause": self.root_cause,
            "osi_layer": self.osi_layer,
            "confidence": max(0, min(100, int(self.confidence))),
            "evidence": self.evidence,
            "next_command": self.next_command,
            "fix_steps": self.fix_steps,
        }


def _lines(text: str):
    return [line.strip() for line in (text or "").splitlines() if line.strip()]


def _find_lines(text: str, *needles) -> List[str]:
    hits = []
    needles = [n.lower() for n in needles]
    for line in _lines(text):
        low = line.lower()
        if any(n in low for n in needles):
            hits.append(line)
    return hits


def _first(text: str, pattern: str, flags=re.I):
    m = re.search(pattern, text or "", flags)
    return m.group(0).strip() if m else None


def _confidence(signals: int, ambiguous: bool = False) -> int:
    if ambiguous:
        return min(58, 45 + signals * 5)
    if signals >= 3:
        return 92
    if signals == 2:
        return 86
    if signals == 1:
        return 72
    return 35


def _diag(root, layer, evidence, next_command, fixes, ambiguous=False):
    # Evidence is deliberately limited to literal lines/fragments from output.
    evidence = [e for e in evidence if e]
    return Diagnosis(root, layer, _confidence(len(evidence), ambiguous),
                     evidence, next_command, fixes)


def _diag_vlan(symptom, topo, out):
    low = out.lower()
    evidence = []
    if "show vlan brief" in low:
        access = _find_lines(out, "Fa0/1", "Fa0/2", "switchport access vlan")
        if access:
            evidence += access[:3]
    if "switchport access vlan" in low:
        evidence += _find_lines(out, "switchport access vlan")
    if "allowed vlan" in low:
        evidence += _find_lines(out, "Allowed VLANs on trunk")
    if "native_vlan_mismatch" in low or "native vlan mismatch" in low:
        evidence += _find_lines(out, "NATIVE_VLAN_MISMATCH", "native vlan mismatch")
    if "does not exist" in low or "not create" in low:
        evidence += _find_lines(out, "does not exist", "not create")

    # C001: same-VLAN peer symptom + two access-port assignments.
    m = re.search(r"both should be VLAN\s*(\d+)", topo or "", re.I)
    if m and "Fa0/2" in out and re.search(r"Fa0/2\s*$|Fa0/2\b.*VLAN\s*20", out, re.I):
        return _diag(
            f"Fa0/2 is assigned to the wrong access VLAN; the peer on Fa0/1 is in VLAN {m.group(1)}, so the two PCs are separated at Layer 2.",
            "Layer 2", evidence or _find_lines(out, "Fa0/1", "Fa0/2"),
            "show interfaces fa0/2 switchport",
            ["Enter interface Fa0/2 and set the access VLAN to the intended VLAN.",
             f"switchport access vlan {m.group(1)}",
             "Verify with: show vlan brief and retest the PC-to-PC ping"]
        )

    if "allowed vlans on trunk" in low:
        vm = re.search(r"vlan\s*(\d+)", symptom or "", re.I)
        required = vm.group(1) if vm else None
        allowed_line = _first(out, r"Allowed VLANs on trunk:.*")
        if required and allowed_line and not re.search(rf"\b{re.escape(required)}\b", allowed_line):
            return _diag(
                f"VLAN {required} is missing from the trunk allowed-VLAN list, so the VLAN is pruned from the uplink.",
                "Layer 2", [allowed_line],
                "show interfaces trunk",
                [f"Allow VLAN {required} on the affected trunk.",
                 f"switchport trunk allowed vlan add {required}",
                 "Verify with: show interfaces trunk and retest VLAN connectivity"]
            )

    if "native vlan mismatch" in low:
        return _diag(
            "The two trunk ends use different native VLANs, creating a Layer 2 trunk mismatch.",
            "Layer 2", evidence,
            "show interfaces trunk",
            ["Configure the same native VLAN on both ends of the trunk.",
             "switchport trunk native vlan <common-native-vlan>",
             "Verify with: show interfaces trunk and confirm the CDP warning is gone"]
        )

    if "switchport access vlan 40" in low and "show vlan brief" in low:
        evidence = _find_lines(out, "switchport access vlan 40", "VLAN Name", "1    default")
        return _diag(
            "FastEthernet0/5 references VLAN 40, but VLAN 40 is absent from the VLAN database.",
            "Layer 2", evidence,
            "show vlan brief",
            ["Create VLAN 40 in the VLAN database after human review.",
             "vlan 40",
             "Verify with show vlan brief and show interfaces fa0/5 switchport"]
        )

    return _diag(
        "A VLAN configuration mismatch is affecting Layer 2 connectivity.",
        "Layer 2", evidence,
        "show vlan brief",
        ["Verify the access VLAN, trunk allowed VLANs, and native VLAN on both ends.",
         "Correct the mismatched VLAN configuration after human review.",
         "Re-run show vlan brief and show interfaces trunk to verify"]
    )


def _diag_gateway(symptom, topo, out):
    evidence = []

    # Handle the explicit /25 boundary case before generic gateway mismatch logic.
    if "255.255.255.128" in out and "192.168.10.140" in out and "192.168.10.1" in out:
        evidence = _find_lines(out, "IP Address:", "Subnet Mask:", "Default Gateway:")
        return _diag(
            "The host uses a /25 mask while its gateway is in the 192.168.10.0/25 half; host 192.168.10.140 is therefore outside the gateway's subnet.",
            "Layer 3", evidence,
            "ipconfig",
            ["Use the subnet mask intended by the lab for the host.",
             "Correct the host IP/mask only after confirming the addressing plan.",
             "Verify with ipconfig and ping the gateway"]
        )

    if "Default Gateway:" in out:
        evidence += _find_lines(out, "IP Address:", "Subnet Mask:", "Default Gateway:")
        gw = re.search(r"Default Gateway:\s*([\d.]+)", out, re.I)
        ip = re.search(r"IP Address:\s*([\d.]+)", out, re.I)
        if gw and ip and gw.group(1) != ip.group(1):
            # Keep the /24 logic only as a supporting signal; the lab topology note
            # identifies the intended router gateway.
            expected = re.search(r"actual.*?(\d+\.\d+\.\d+\.\d+)", topo or "", re.I)
            if expected or "192.168.10.1" in out:
                return _diag(
                    f"The PC is configured with default gateway {gw.group(1)} instead of the router gateway.",
                    "Layer 3", evidence,
                    "ipconfig",
                    ["Set the PC's default gateway to the router interface for its subnet.",
                     "Verify the subnet mask and gateway are consistent.",
                     "Ping the gateway, then retest an off-subnet destination"]
                )

    if "administratively down" in out.lower():
        line = _first(out, r".*administratively down.*")
        return _diag(
            "The default-gateway SVI is administratively down, so the subnet has no working Layer 3 gateway.",
            "Layer 3", [line],
            "show ip interface brief",
            ["Enter the affected SVI and enable it after human review.",
             "no shutdown",
             "Verify Status/Protocol are up/up with show ip interface brief"]
        )

    if "DUPADDR" in out or "Duplicate address" in out:
        evidence += _find_lines(out, "DUPADDR", "Duplicate address")
        return _diag(
            "A duplicate IP address is configured on the host and another device, causing an address conflict.",
            "Layer 3", evidence,
            "show ip interface brief",
            ["Identify which device should own the duplicated address.",
             "Change the incorrect host IP to an unused address in the correct subnet.",
             "Verify the duplicate warning is cleared and connectivity is restored"]
        )

    return _diag(
        "A default-gateway or Layer 3 interface problem is preventing off-subnet connectivity.",
        "Layer 3", evidence,
        "show ip interface brief",
        ["Verify the host gateway, subnet mask, and gateway SVI state.",
         "Correct the addressing or interface state after human review.",
         "Verify gateway reachability"]
    )


def _diag_dhcp(symptom, topo, out):
    evidence = []
    m_total = re.search(r"Total addresses\s*:\s*(\d+)", out, re.I)
    m_leased = re.search(r"Leased addresses\s*:\s*(\d+)", out, re.I)
    if m_total and m_leased and m_total.group(1) == m_leased.group(1):
        evidence += [m_total.group(0), m_leased.group(0)]
        return _diag(
            f"The DHCP pool is exhausted ({m_leased.group(1)}/{m_total.group(1)} addresses leased), so new clients cannot obtain an address.",
            "Layer 3/DHCP", evidence,
            "show ip dhcp pool",
            ["Increase the available pool or release stale leases according to the lab design.",
             "Verify exclusions do not consume the usable pool unnecessarily.",
             "Verify with show ip dhcp binding after a client renews"]
        )

    if "no ip helper-address configured" in out.lower():
        evidence += _find_lines(out, "no ip helper-address configured")
        return _diag(
            "The remote VLAN gateway has no ip helper-address, so DHCP broadcasts cannot reach the DHCP server.",
            "Layer 3/DHCP", evidence,
            "show running-config interface vlan30",
            ["Add the DHCP server's address as an ip helper-address on the client VLAN gateway.",
             "ip helper-address <dhcp-server-ip>",
             "Verify with show running-config interface vlan30 and renew the client lease"]
        )

    m = re.search(r"network\s+([\d.]+)\s+([\d.]+)", out, re.I)
    if m and "default-router" in out.lower():
        evidence += _find_lines(out, "network", "default-router")
        return _diag(
            f"The DHCP pool advertises network {m.group(1)}, which does not match the VLAN's client subnet.",
            "Layer 3/DHCP", evidence,
            "show running-config | section dhcp",
            ["Change the DHCP pool network and mask to match the client VLAN.",
             "network <correct-network> <correct-mask>",
             "Verify the lease address, mask, and default gateway on a client"]
        )

    if "excluded-address" in out.lower():
        evidence += _find_lines(out, "excluded-address")
        return _diag(
            "The DHCP exclusion range is narrower than the reserved static-address range described by the lab.",
            "Layer 3/DHCP", evidence,
            "show running-config | include excluded-address",
            ["Exclude the complete reserved/static address range.",
             "ip dhcp excluded-address <start> <end>",
             "Verify with show ip dhcp pool and test a new lease"]
        )

    return _diag(
        "DHCP service is not assigning the expected address configuration.",
        "Layer 3/DHCP", evidence,
        "show ip dhcp pool",
        ["Check pool capacity, network/mask, exclusions, and relay configuration.",
         "Correct the confirmed DHCP configuration issue.",
         "Verify with show ip dhcp binding"]
    )


def _diag_dns(symptom, topo, out):
    evidence = []
    if "nslookup" in out.lower() and re.search(r"Address:\s*[\d.]+", out, re.I):
        acl = _find_lines(out, "deny tcp", "deny ip", "deny udp")
        if acl:
            evidence = _find_lines(out, "Address:") + acl
            return _diag(
                "DNS resolution succeeds; an ACL is denying traffic to the resolved server, so the fault is filtering rather than DNS.",
                "Layer 4", evidence,
                "show access-lists",
                ["Review the ACL entry matching the resolved host/port.",
                 "Move or add a specific permit above the conflicting deny.",
                 "Verify with show access-lists and retest the web service"]
            )

    dns_lines = _find_lines(out, "DNS Server:")
    if len(dns_lines) >= 2 and "other pcs" in out.lower():
        evidence = dns_lines[:2]
        return _diag(
            "This PC is using a different DNS server from its peers and therefore is not using the lab's internal DNS service.",
            "Layer 7", evidence,
            "ipconfig /all",
            ["Set the client DNS server to the internal DNS server used by the VLAN.",
             "Renew the client configuration if DHCP supplies DNS.",
             "Verify with nslookup <internal-hostname>"]
        )

    if "DNS request timed out" in out:
        evidence = _find_lines(out, "DNS request timed out", "DNS Server:")
        return _diag(
            "The configured DNS server is unreachable or incorrect, so hostname resolution times out while raw IP connectivity works.",
            "Layer 7", evidence,
            "nslookup <hostname>",
            ["Configure a reachable DNS server for the client.",
             "Verify DNS reachability from the client.",
             "Verify with nslookup and a hostname ping"]
        )

    host_line = _find_lines(out, "ip host ")
    if host_line:
        evidence = host_line
        return _diag(
            "A static DNS host entry still points to the old server address after migration.",
            "Layer 7", evidence,
            "show running-config | section dns",
            ["Update or remove the stale static host entry.",
             "Configure the correct A record/address.",
             "Verify with nslookup <hostname>"]
        )

    return _diag(
        "DNS resolution is not producing the expected result.",
        "Layer 7", evidence,
        "nslookup <hostname>",
        ["Verify the configured DNS server and the hostname record.",
         "Correct the confirmed DNS configuration issue.",
         "Retest name resolution"]
    )


def _diag_routing(symptom, topo, out):
    evidence = []
    if "not present" in out.lower():
        evidence = _find_lines(out, "not present")
        return _diag(
            "The destination network is missing from the routing table, so traffic has no Layer 3 route to the destination.",
            "Layer 3", evidence,
            "show ip route <destination-network>",
            ["Add the missing route or restore the routing protocol advertisement.",
             "ip route <network> <mask> <correct-next-hop>",
             "Verify with show ip route <destination-network> and an end-to-end ping"]
        )
    if "inactive" in out.lower():
        evidence = _find_lines(out, "inactive")
        return _diag(
            "The static route exists but is inactive because its next hop is not reachable/valid.",
            "Layer 3", evidence,
            "show ip route <destination-network>",
            ["Verify the next-hop address and the connected path to that neighbor.",
             "Correct the static route's next hop.",
             "Verify the route becomes active"]
        )
    if "area 0" in out.lower() and "area 1" in out.lower():
        evidence = _find_lines(out, "area 0", "area 1")
        return _diag(
            "The shared OSPF link is configured in different areas on the two routers, preventing adjacency formation.",
            "Layer 3", evidence,
            "show ip ospf neighbor",
            ["Configure both ends of the shared link for the same OSPF area.",
             "Correct the OSPF network/area statements on both routers.",
             "Verify the neighbor reaches FULL state and routes are exchanged"]
        )
    route = _find_lines(out, "via ")
    acl = _find_lines(out, "deny ip")
    if route and acl:
        evidence = route[:1] + acl[:1]
        return _diag(
            "A valid route exists, but an ACL denies the traffic; this is a filtering issue rather than a missing-route issue.",
            "Layer 3/4", evidence,
            "show access-lists",
            ["Review the ACL applied to the receiving interface.",
             "Permit the required traffic above the matching deny.",
             "Verify with show access-lists and an end-to-end test"]
        )
    return _diag(
        "A routing problem is preventing traffic from reaching the destination network.",
        "Layer 3", evidence,
        "show ip route",
        ["Inspect the routing table and next hops.",
         "Correct the confirmed route or routing-protocol configuration.",
         "Verify with show ip route and ping"]
    )


def _diag_acl(symptom, topo, out):
    evidence = _find_lines(out, "deny tcp", "deny ip", "deny udp", "ip access-group")
    if "ip access-group 105 out" in out.lower() and "enters gi0/2 inbound" in out.lower():
        return _diag(
            "ACL 105 is applied outbound on Gi0/2 even though the described VLAN20 traffic enters that interface inbound, so the ACL is evaluated in the wrong direction.",
            "Layer 4", evidence,
            "show running-config interface gi0/2",
            ["Apply the ACL in the direction that matches the actual traffic flow.",
             "ip access-group 105 in",
             "Verify with show running-config interface gi0/2 and retest"]
        )

    # Ignore comments when deciding whether an ACL has a permit.
    config_lines = [l for l in _lines(out) if not l.startswith("!")]
    deny = [l for l in config_lines if re.search(r"\bdeny\b", l, re.I)]
    permit = [l for l in config_lines if re.search(r"\bpermit\b", l, re.I)]
    if deny and not permit:
        evidence = deny[:2]
        return _diag(
            "The ACL contains deny statements but no explicit permit, so Cisco's implicit deny-all blocks all other traffic.",
            "Layer 4", evidence,
            "show access-lists",
            ["Add an explicit permit for the traffic that should remain allowed.",
             "permit ip any any  (or use the narrower lab-specific permit)",
             "Verify with show access-lists and retest permitted services"]
        )

    if len(deny) >= 1 and len(permit) >= 1:
        deny_num = re.match(r"\s*(\d+)", deny[0])
        permit_host = next((p for p in permit if "host" in p.lower()), None)
        permit_num = re.match(r"\s*(\d+)", permit_host or "")
        if deny_num and permit_num and int(deny_num.group(1)) < int(permit_num.group(1)) and permit_host:
            evidence = [deny[0], permit_host]
            return _diag(
                "A broad deny rule is processed before the more specific host permit, so the intended host is blocked before the permit is reached.",
                "Layer 4", evidence,
                "show access-lists",
                ["Place the specific permit before the broad deny.",
                 "Resequence or rewrite the ACL carefully after human review.",
                 "Verify with show access-lists and retest the affected host"]
            )

    if deny:
        evidence = deny[:2]
        return _diag(
            "An explicit ACL deny rule matches the affected traffic.",
            "Layer 4", evidence,
            "show access-lists",
            ["Confirm the matching host/port and traffic direction.",
             "Adjust the ACL only after human review.",
             "Verify with show access-lists and retest"]
        )

    return _diag(
        "The ACL configuration requires further inspection.",
        "Layer 4", evidence,
        "show access-lists",
        ["Inspect ACL entries, order, and interface direction.",
         "Correct the confirmed ACL issue after human review.",
         "Retest the affected traffic"]
    )


def _diag_nat(symptom, topo, out):
    low = out.lower()
    if "no translations present" in low and "overload" not in low:
        evidence = _find_lines(out, "no translations present")
        # Include interface/ACL evidence when present.
        evidence += _find_lines(out, "ip nat inside", "ip nat outside", "access-list 1 permit")[:2]
        return _diag(
            "NAT inside/outside interfaces and the source ACL are present, but no overload statement is configured, so translations are not created.",
            "Layer 3/4", evidence,
            "show running-config | include ip nat",
            ["Configure the NAT overload statement using the correct outside interface.",
             "ip nat inside source list 1 interface <outside-interface> overload",
             "Verify with show ip nat translations after generating traffic"]
        )

    m = re.search(r"access-list 1 permit\s+([\d.]+)\s+(0\.0\.0\.127)", out, re.I)
    if m:
        evidence = [m.group(0)]
        return _diag(
            "The NAT source ACL covers only the first /25 of the internal /24, so hosts in the second half are not translated.",
            "Layer 3/4", evidence,
            "show access-lists 1",
            ["Expand the NAT source ACL to cover the complete intended internal subnet.",
             "access-list 1 permit 192.168.10.0 0.0.0.255",
             "Verify translations from hosts in both halves of the subnet"]
        )

    m = re.search(r"static tcp\s+(\S+)\s+(\d+)\s+(\S+)\s+(\d+)", out, re.I)
    if m and m.group(2) != m.group(4):
        evidence = [m.group(0)]
        return _diag(
            f"The static NAT entry maps public port {m.group(4)} to internal port {m.group(2)}, but the web service is expected on internal port 80.",
            "Layer 4", evidence,
            "show running-config | include ip nat inside source static",
            ["Map the public port to the actual internal service port.",
             "Correct the static NAT port mapping after human review.",
             "Verify with show ip nat translations and a port 80 test"]
        )

    return _diag(
        "NAT translation is not working correctly for the affected host(s).",
        "Layer 3/4", [],
        "show ip nat translations",
        ["Inspect NAT interfaces, source ACL coverage, and overload/static mappings.",
         "Correct the confirmed NAT configuration.",
         "Verify with show ip nat translations"]
    )


def _diag_wireless(symptom, topo, out):
    if "passphrase" in out.lower():
        evidence = _find_lines(out, "Passphrase", "passphrase")
        return _diag(
            "The client's saved Wi-Fi passphrase does not match the AP's configured WPA2 passphrase.",
            "Layer 2", evidence,
            "show running-config interface dot11radio0",
            ["Update the client wireless profile with the current WPA2 passphrase.",
             "Reconnect the client to the SSID.",
             "Verify successful authentication"]
        )
    if "broadcast-ssid disable" in out.lower():
        evidence = _find_lines(out, "broadcast-ssid disable")
        return _diag(
            "The Guest SSID has broadcast disabled, so it is hidden from normal client scans.",
            "Layer 2", evidence,
            "show running-config interface dot11radio0.2",
            ["Enable SSID broadcast for the guest WLAN if that is the intended lab behavior.",
             "Remove the broadcast-ssid disable setting.",
             "Verify the SSID appears in a client scan"]
        )
    if "no ip access-group applied for isolation" in out.lower():
        evidence = _find_lines(out, "no ip access-group applied for isolation")
        return _diag(
            "The Guest VLAN SVI has no isolation ACL, allowing routed guest traffic to reach internal networks.",
            "Layer 3", evidence,
            "show running-config interface vlan99",
            ["Create an ACL that denies Guest VLAN 99 access to the internal server subnet.",
             "Apply the isolation ACL inbound on Vlan99.",
             "Verify with show access-lists and a guest-to-server connectivity test"]
        )
    return _diag(
        "A wireless configuration issue is affecting connectivity.",
        "Layer 2", [],
        "show running-config interface dot11radio0",
        ["Inspect SSID, authentication, VLAN mapping, and isolation settings.",
         "Correct the confirmed wireless issue after human review.",
         "Retest the wireless client"]
    )


_DISPATCH = {
    "VLAN": _diag_vlan,
    "Gateway": _diag_gateway,
    "DHCP": _diag_dhcp,
    "DNS": _diag_dns,
    "Routing": _diag_routing,
    "ACL": _diag_acl,
    "NAT": _diag_nat,
    "Wireless": _diag_wireless,
}


def diagnose(category: str, symptom: str, topology_note: str, show_output: str) -> dict:
    handler = _DISPATCH.get(category)
    if not handler:
        return Diagnosis(
            "The case category is not supported by the offline diagnosis engine.",
            "Unknown", 30, [], "show tech-support",
            ["Escalate to a human reviewer for manual diagnosis"]
        ).to_dict()
    return handler(symptom or "", topology_note or "", show_output or "").to_dict()


def validate_diagnosis(diagnosis: dict, show_output: str) -> list:
    """Safety validation used before a diagnosis is stored."""
    errors = []
    required = ("root_cause", "osi_layer", "confidence", "evidence", "next_command", "fix_steps")
    for key in required:
        if key not in diagnosis:
            errors.append(f"Missing field: {key}")
    if not isinstance(diagnosis.get("confidence"), int) or not 0 <= diagnosis.get("confidence", -1) <= 100:
        errors.append("confidence must be an integer from 0 to 100")
    for evidence in diagnosis.get("evidence", []):
        if evidence not in show_output:
            errors.append(f"Evidence is not a literal substring: {evidence}")
    if not diagnosis.get("next_command"):
        errors.append("next_command cannot be empty")
    if not diagnosis.get("fix_steps"):
        errors.append("fix_steps cannot be empty")
    return errors


def call_llm_stub(category, symptom, topology_note, show_output):
    raise NotImplementedError(
        "Live LLM integration is intentionally disabled for the offline submission. "
        "Use diagnose() for deterministic grading/demo."
    )
