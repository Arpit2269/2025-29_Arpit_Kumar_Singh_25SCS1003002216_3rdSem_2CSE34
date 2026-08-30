import csv
import os

cases = []

def add(cid, category, severity, symptom, topology, show_output, expected_fault, osi_layer, concept):
    cases.append({
        "case_id": cid,
        "category": category,
        "severity": severity,
        "symptom": symptom,
        "topology_note": topology,
        "show_output": show_output,
        "expected_fault": expected_fault,
        "osi_layer": osi_layer,
        "concept": concept
    })

# ---------------- VLAN (5) ----------------
add("C001","VLAN","High",
    "PC1 (VLAN 10) cannot ping PC2 (VLAN 10) on the same switch.",
    "SW1 access switch, Fa0/1=PC1, Fa0/2=PC2, both should be VLAN10.",
    "show vlan brief\nVLAN Name    Status  Ports\n1    default  active  Fa0/3,Fa0/4\n10   Sales    active  Fa0/1\n20   HR       active  Fa0/2",
    "Fa0/2 is assigned to VLAN 20 instead of VLAN 10 (access VLAN misconfigured).",
    "Layer 2",
    "vlan_access_port_mismatch")

add("C002","VLAN","High",
    "All PCs in VLAN 30 lost connectivity to the VLAN 30 server on the other switch.",
    "SW1---trunk(Gi0/1)---SW2, VLAN30 server hangs off SW2.",
    "show interfaces trunk\nPort   Mode  Encapsulation  Status   Native vlan\nGi0/1  on    802.1q         trunking 1\n\nAllowed VLANs on trunk: 1,10,20",
    "VLAN 30 is not included in the allowed VLAN list on the Gi0/1 trunk.",
    "Layer 2",
    "trunk_allowed_vlan_missing")

add("C003","VLAN","Medium",
    "New VLAN 40 hosts get link light but cannot reach anything, even ARP fails.",
    "SW1, Fa0/5 assigned to vlan 40, but VLAN 40 was never created.",
    "show vlan brief\nVLAN Name    Status  Ports\n1    default  active  Fa0/1-4\n\nshow running-config interface fa0/5\ninterface FastEthernet0/5\n switchport access vlan 40\n switchport mode access",
    "VLAN 40 does not exist in the VLAN database, so the port is inactive for that VLAN.",
    "Layer 2",
    "vlan_not_created")

add("C004","VLAN","Low",
    "CDP native VLAN mismatch warning appears on SW1 and SW2 console.",
    "Trunk link between SW1 and SW2 Gi0/2.",
    "%CDP-4-NATIVE_VLAN_MISMATCH: Native VLAN mismatch discovered on GigabitEthernet0/2 (1), with Switch2 GigabitEthernet0/2 (99).",
    "Native VLAN on Gi0/2 is set to VLAN 1 on SW1 but VLAN 99 on SW2.",
    "Layer 2",
    "native_vlan_mismatch")

add("C005","VLAN","High",
    "PC in VLAN 30 gets an IP from DHCP but cannot reach anything, including its own gateway.",
    "SW1 Fa0/6 access vlan 30, trunk to distribution switch carries only vlan 1,10,20.",
    "show interfaces trunk\nAllowed VLANs on trunk: 1,10,20\n\nshow vlan brief\nVLAN 30   Sales30   active   Fa0/6",
    "VLAN 30 exists locally but is pruned from the uplink trunk, isolating the VLAN from the rest of the network.",
    "Layer 2",
    "trunk_allowed_vlan_missing")

# ---------------- Gateway (4) ----------------
add("C006","Gateway","High",
    "PC1 can ping other devices in its own subnet but cannot reach anything outside, including the gateway.",
    "PC1 192.168.10.10/24, router SVI 192.168.10.1.",
    "PC> ipconfig\nIP Address: 192.168.10.10\nSubnet Mask: 255.255.255.0\nDefault Gateway: 192.168.10.254\n\nPC> ping 192.168.10.1\nRequest timed out.",
    "Default gateway configured on PC1 (192.168.10.254) does not match the router's actual interface IP (192.168.10.1).",
    "Layer 3",
    "wrong_default_gateway")

add("C007","Gateway","Critical",
    "PC gets an IP but 'gateway ping works' intermittently fails and inter-VLAN routing is completely down.",
    "L3 switch, VLAN10 SVI should route between VLAN10 and VLAN20.",
    "show ip interface brief\nInterface              IP-Address      Status                Protocol\nVlan10                 192.168.10.1    administratively down up",
    "The Vlan10 SVI (default gateway for VLAN10) is administratively shut down.",
    "Layer 3",
    "svi_interface_down")

add("C008","Gateway","High",
    "Two PCs on the same subnet have intermittent connectivity and IP conflict warnings.",
    "PC1 and the router's gateway interface share the same IP by mistake.",
    "PC> ipconfig\nIP Address: 192.168.10.1\n\n%SYS-3-DUPADDR: Duplicate address 192.168.10.1 on FastEthernet0/0",
    "PC1 is statically configured with the same IP address as the router's gateway interface, causing a duplicate IP conflict.",
    "Layer 3",
    "duplicate_ip_gateway")

add("C009","Gateway","Medium",
    "PC can reach some hosts in the same building but times out reaching the gateway and everything beyond it.",
    "PC configured with /25 mask while the rest of the subnet uses /24.",
    "PC> ipconfig\nIP Address: 192.168.10.140\nSubnet Mask: 255.255.255.128\nDefault Gateway: 192.168.10.1",
    "PC subnet mask (/25) places it in a different subnet than the gateway (192.168.10.1 is in the 192.168.10.0/25 half but .140 falls in the second /25 block), so the gateway is unreachable.",
    "Layer 3",
    "wrong_subnet_mask")

# ---------------- DHCP (4) ----------------
add("C010","DHCP","High",
    "New PCs in VLAN 20 fail to get an IP address; older PCs still work fine.",
    "Router-on-a-stick doing DHCP for VLAN20 pool of only 5 addresses.",
    "show ip dhcp pool VLAN20\nPool VLAN20 :\n Utilization mark (high/low)    : 100 / 0\n Total addresses                : 5\n Leased addresses               : 5\n Excluded addresses             : 1",
    "The DHCP pool for VLAN20 is exhausted (5 of 5 addresses leased), so new clients cannot obtain an address.",
    "Layer 3/DHCP",
    "dhcp_pool_exhausted")

add("C011","DHCP","Critical",
    "All PCs in VLAN 30 (different subnet from the DHCP server) fail to receive an IP address.",
    "DHCP server lives in VLAN10; VLAN30 clients are one router hop away.",
    "show running-config interface vlan30\ninterface Vlan30\n ip address 192.168.30.1 255.255.255.0\n! no ip helper-address configured",
    "The VLAN30 gateway interface has no 'ip helper-address' pointing to the DHCP server, so DHCP broadcasts never reach it.",
    "Layer 3/DHCP",
    "missing_ip_helper_address")

add("C012","DHCP","Medium",
    "PCs in VLAN 20 receive an IP address but it is unreachable from the rest of the network.",
    "DHCP pool network statement configured with wrong subnet.",
    "show running-config | section dhcp pool VLAN20\nip dhcp pool VLAN20\n network 192.168.200.0 255.255.255.0\n default-router 192.168.20.1",
    "The DHCP pool network (192.168.200.0/24) does not match the actual VLAN20 subnet (192.168.20.0/24), handing out unusable addresses.",
    "Layer 3/DHCP",
    "dhcp_pool_wrong_network")

add("C013","DHCP","Low",
    "Server and printer at fixed addresses .1-.10 are randomly handed out to new laptops, causing IP conflicts.",
    "DHCP pool covers .1-.254 but exclusion range was set incorrectly.",
    "show running-config | include excluded-address\nip dhcp excluded-address 192.168.10.1 192.168.10.1",
    "Only 192.168.10.1 is excluded; the intended range 192.168.10.1-192.168.10.10 (reserved for static devices) was not fully excluded.",
    "Layer 3/DHCP",
    "dhcp_exclusion_range_wrong")

# ---------------- DNS (4) ----------------
add("C014","DNS","Medium",
    "PC can ping the web server by IP address but 'ping www.netsage.local' fails to resolve.",
    "PC configured to use an unreachable DNS server.",
    "PC> ping 8.8.8.8\nReply from 8.8.8.8: bytes=32 time=1ms\n\nPC> ping www.netsage.local\nPinging www.netsage.local ... DNS request timed out.\n\nPC> ipconfig\nDNS Server: 192.168.99.99",
    "The configured DNS server (192.168.99.99) is unreachable/incorrect, so name resolution fails while raw IP connectivity works.",
    "Layer 7",
    "dns_server_unreachable")

add("C015","DNS","Low",
    "One PC in the lab cannot resolve internal hostnames while every other PC in the same VLAN can.",
    "This PC has a manually typed DNS entry that differs from DHCP-assigned peers.",
    "PC> ipconfig\nDNS Server: 8.8.8.8\n\n(other PCs)\nDNS Server: 192.168.10.5 (internal DNS)",
    "This PC is statically configured with a public DNS server instead of the internal DNS server that hosts the .local records.",
    "Layer 7",
    "wrong_dns_server_configured")

add("C016","DNS","Medium",
    "DNS resolves the web server name correctly but the website still does not load in the browser.",
    "Name resolves to 192.168.30.10, but an ACL on the distribution router blocks port 80 to that host.",
    "PC> nslookup www.netsage.local\nName: www.netsage.local\nAddress: 192.168.30.10\n\nshow access-lists\nExtended IP access list 101\n 10 deny tcp any host 192.168.30.10 eq 80\n 20 permit ip any any",
    "DNS resolution succeeds, but an ACL is denying TCP port 80 to the resolved server IP, so this is not actually a DNS fault.",
    "Layer 4",
    "dns_ok_acl_blocking")

add("C017","DNS","Medium",
    "Internal clients can resolve www.netsage.local but it points to the wrong (old) server IP after a server migration.",
    "DNS server still has a stale A record for the web server.",
    "show running-config | section dns\nip dns server\n\nip host www.netsage.local 192.168.30.10",
    "A static DNS host entry still maps www.netsage.local to the old server IP (192.168.30.10) instead of the new one, causing clients to reach the decommissioned host.",
    "Layer 7",
    "stale_dns_record")

# ---------------- Routing (4) ----------------
add("C018","Routing","High",
    "PC gets an IP but cannot reach a server in VLAN 30; gateway ping works.",
    "R1 has routes to VLAN10 and VLAN20 but VLAN30 network was never added.",
    "show ip route\nC  192.168.10.0/24 is directly connected, Vlan10\nC  192.168.20.0/24 is directly connected, Vlan20\n! 192.168.30.0/24 not present",
    "There is no route to 192.168.30.0/24 in the routing table, so traffic to VLAN30 is unreachable beyond the local gateway.",
    "Layer 3",
    "missing_static_route")

add("C019","Routing","Medium",
    "Remote branch (192.168.40.0/24) is unreachable even though a static route for it exists.",
    "Static route configured with the wrong next-hop address.",
    "show running-config | include ip route\nip route 192.168.40.0 255.255.255.0 192.168.1.254\n\nshow ip route\nS  192.168.40.0/24 [1/0] via 192.168.1.254, inactive",
    "The static route's next-hop (192.168.1.254) is not a valid/reachable neighbor, so the route stays inactive.",
    "Layer 3",
    "wrong_next_hop_static_route")

add("C020","Routing","High",
    "OSPF neighbors on R1 and R2 never form (stuck in EXSTART/DOWN); no routes are exchanged.",
    "R1 area 0, R2 area 1 on the shared link by mistake.",
    "show ip ospf neighbor\n(no output - neighbor table empty)\n\nshow ip protocols\nRouting for Networks:\n 10.0.0.0 0.0.0.255 area 0 (R1)\n 10.0.0.0 0.0.0.255 area 1 (R2)",
    "R1 and R2 advertise the shared link in mismatched OSPF areas (area 0 vs area 1), preventing adjacency formation.",
    "Layer 3",
    "ospf_area_mismatch")

add("C021","Routing","Medium",
    "A valid route exists to the destination but traffic is still being silently dropped end to end.",
    "Correct static route present, but an inbound ACL on the receiving interface denies the traffic.",
    "show ip route\nS  192.168.50.0/24 [1/0] via 10.0.0.2\n\nshow ip access-lists\nExtended IP access list BLOCK_50\n 10 deny ip 192.168.10.0 0.0.0.255 192.168.50.0 0.0.0.255\n 20 permit ip any any\n\nshow running-config interface gi0/1\n ip access-group BLOCK_50 in",
    "Routing is correct, but an ACL applied inbound on Gi0/1 is denying the traffic, which is a security/filtering fault, not a routing fault.",
    "Layer 3/4",
    "route_ok_acl_blocking")

# ---------------- ACL (4) ----------------
add("C022","ACL","High",
    "PC1 (192.168.10.10) cannot SSH to the server, but every other PC in VLAN 10 can.",
    "Extended ACL applied to block only PC1 by IP.",
    "show access-lists\nExtended IP access list SSH_BLOCK\n 10 deny tcp host 192.168.10.10 any eq 22\n 20 permit ip any any",
    "An extended ACL explicitly denies TCP port 22 (SSH) from PC1's specific IP address.",
    "Layer 4",
    "acl_blocking_specific_host")

add("C023","ACL","Medium",
    "An ACL intended to restrict outbound traffic from VLAN20 seems to have no effect at all.",
    "ACL 105 written correctly but applied to the wrong interface/direction.",
    "show running-config interface gi0/2\n ip access-group 105 out\n\n! Traffic from VLAN20 actually enters gi0/2 inbound, not outbound",
    "ACL 105 is applied in the 'out' direction on Gi0/2, but VLAN20 traffic enters that interface inbound, so the ACL never evaluates it.",
    "Layer 4",
    "acl_wrong_direction")

add("C024","ACL","High",
    "Users report that ALL traffic through R1, even permitted services, is being blocked after a recent ACL change.",
    "New ACL applied to interface with only deny statements, no explicit permit.",
    "show access-lists\nExtended IP access list LOCKDOWN\n 10 deny tcp any any eq 23\n 20 deny tcp any any eq 21\n! no permit statement present -> implicit deny any any",
    "The ACL has no explicit 'permit ip any any' at the end, so the implicit deny-all rule blocks every other type of traffic.",
    "Layer 4",
    "acl_implicit_deny_all")

add("C025","ACL","Medium",
    "A specific host (192.168.10.50) that should be allowed HTTP access is still being blocked, even though a permit line exists for it.",
    "ACL has a broad deny statement listed before the specific permit statement.",
    "show access-lists\nExtended IP access list WEBACCESS\n 10 deny tcp 192.168.10.0 0.0.0.255 any eq 80\n 20 permit tcp host 192.168.10.50 any eq 80\n 30 permit ip any any",
    "ACLs are processed top-down; the broad deny for the whole 192.168.10.0/24 subnet on line 10 matches first and blocks 192.168.10.50 before the specific permit on line 20 is ever reached.",
    "Layer 4",
    "acl_rule_order_issue")

# ---------------- NAT (3) ----------------
add("C026","NAT","High",
    "Internal LAN hosts (192.168.10.0/24) cannot reach any internet-simulated server outside the router.",
    "Router has NAT ACL and inside/outside interfaces defined but 'ip nat inside source' overload command missing.",
    "show ip nat translations\n(no translations present)\n\nshow running-config | include nat\ninterface Gi0/0\n ip nat inside\ninterface Gi0/1\n ip nat outside\naccess-list 1 permit 192.168.10.0 0.0.0.255",
    "NAT interfaces and the source ACL are defined, but there is no 'ip nat inside source list 1 interface Gi0/1 overload' statement, so no translation actually occurs.",
    "Layer 3/4",
    "nat_overload_not_configured")

add("C027","NAT","Medium",
    "Only some internal hosts can reach the outside network through NAT; others get no response.",
    "NAT source ACL only covers half of the internal subnet.",
    "show running-config | include access-list 1\naccess-list 1 permit 192.168.10.0 0.0.0.127\n\n! Hosts .128-.254 are not matched by this ACL",
    "The NAT source access-list only permits the 192.168.10.0/25 half of the subnet, so hosts in the 192.168.10.128/25 range are never translated.",
    "Layer 3/4",
    "nat_acl_incomplete")

add("C028","NAT","Low",
    "External users cannot reach the internal web server via the router's public IP on port 80.",
    "Static NAT configured to the wrong internal port.",
    "show running-config | include ip nat inside source static\nip nat inside source static tcp 192.168.10.10 8080 203.0.113.5 80",
    "The static NAT entry maps the public port 80 to internal port 8080, but the web server is actually listening on port 80 internally, so the translation points to the wrong port.",
    "Layer 4",
    "static_nat_wrong_port")

# ---------------- Wireless (2) ----------------
add("C029","Wireless","Medium",
    "Laptop shows the correct SSID but fails authentication every time it tries to connect.",
    "AP configured with WPA2-PSK; laptop profile has an outdated saved passphrase.",
    "AP config:\ninterface dot11radio0\n encryption mode ciphers aes-ccm\n authentication key-management wpa version 2\n! Passphrase set to 'NetSage2026!'\n\nLaptop wireless profile stored passphrase: 'NetSage2020'",
    "The laptop's saved Wi-Fi passphrase is outdated and no longer matches the AP's configured WPA2 passphrase.",
    "Layer 2",
    "wireless_wrong_passphrase")

add("C030","Wireless","Low",
    "Guest laptops cannot see the 'NetSage-Guest' SSID at all, though staff SSID works fine on the same AP.",
    "Guest SSID broadcast is disabled and mapped to the wrong VLAN.",
    "show running-config interface dot11radio0.2\n encapsulation dot1Q 99\n ssid NetSage-Guest\n  broadcast-ssid disable\n bridge-group 2",
    "The Guest SSID has 'broadcast-ssid disable' set, so it is hidden and does not appear in client scans by default.",
    "Layer 2",
    "wireless_ssid_hidden")

add("C031","Wireless","Medium",
    "Guest Wi-Fi users can reach the internal file server, violating the intended guest isolation policy.",
    "Guest VLAN 99 should be isolated by ACL from internal VLAN10 server subnet.",
    "show running-config interface vlan99\ninterface Vlan99\n ip address 192.168.99.1 255.255.255.0\n! no ip access-group applied for isolation",
    "The Guest VLAN (99) SVI has no isolation ACL applied, allowing routed traffic to reach the internal server subnet.",
    "Layer 3",
    "guest_isolation_failure")

output_path = os.path.join(os.path.dirname(__file__), "cases.csv")
with open(output_path, "w", newline="", encoding="utf-8") as f:
    fieldnames = ["case_id","category","severity","symptom","topology_note","show_output","expected_fault","osi_layer","concept"]
    writer = csv.DictWriter(f, fieldnames=fieldnames)
    writer.writeheader()
    for c in cases:
        writer.writerow(c)

print(f"Wrote {len(cases)} cases")
