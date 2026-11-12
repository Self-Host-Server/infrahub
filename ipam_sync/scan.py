import subprocess
import xml.etree.ElementTree as ET

from ipam_sync.rules import normalize_mac


def parse_nmap(xml: str) -> list[dict]:
    """
    Parse nmap XML output and return list of up hosts with their IPs and MACs.

    Returns [{"ip": str, "mac": str | None}] for each host with status state="up".
    """
    root = ET.fromstring(xml)
    results = []

    for host in root.findall("host"):
        # Check if host status is up
        status = host.find("status")
        if status is None or status.get("state") != "up":
            continue

        # Extract IPv4 address
        ipv4 = None
        for addr in host.findall("address"):
            if addr.get("addrtype") == "ipv4":
                ipv4 = addr.get("addr")
                break

        if ipv4 is None:
            continue

        # Extract MAC address (if present)
        mac = None
        for addr in host.findall("address"):
            if addr.get("addrtype") == "mac":
                mac = normalize_mac(addr.get("addr"))
                break

        results.append({"ip": ipv4, "mac": mac})

    return results


def run_scan(subnets: list[str]) -> list[dict]:
    """
    Run nmap ping scan and return list of up hosts with their IPs and MACs.

    Runs: nmap -sn -n -oX - <subnets...>
    """
    cmd = ["nmap", "-sn", "-n", "-oX", "-"] + subnets
    result = subprocess.run(cmd, check=True, capture_output=True, text=True, timeout=600)
    return parse_nmap(result.stdout)
