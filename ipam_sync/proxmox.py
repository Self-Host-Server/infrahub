import re

import httpx

from ipam_sync.rules import normalize_mac, unique_guest_names

MAC_RE = re.compile(r"^[0-9A-Fa-f]{2}(:[0-9A-Fa-f]{2}){5}$")
NIC_KEY_RE = re.compile(r"^net\d+$")


def parse_net(value: str) -> dict:
    """Parse a Proxmox net string (VM or LXC form) into {"mac": str | None, "ip": str | None}."""
    mac = None
    ip = None
    for pair in value.split(","):
        if "=" not in pair:
            continue
        key, val = pair.split("=", 1)
        if mac is None and MAC_RE.match(val):
            mac = normalize_mac(val)
        if key == "ip":
            ip = None if val in ("dhcp", "manual") else val
    return {"mac": mac, "ip": ip}


def parse_agent(payload: dict) -> dict[str, list[str]]:
    """Map MAC -> list of IPv4 strings from a qemu-guest-agent network-get-interfaces payload."""
    result = {}
    for iface in payload.get("data", {}).get("result", []):
        mac = normalize_mac(iface.get("hardware-address"))
        if mac is None:
            continue
        result[mac] = [addr["ip-address"] for addr in iface.get("ip-addresses", []) if addr.get("ip-address-type") == "ipv4"]
    return result


def fetch_guests(client: httpx.Client) -> list[dict]:
    """Fetch VMs/LXCs (skipping templates) with their NICs, resolving IPs via config and (for qemu) the guest agent."""
    resp = client.get("/api2/json/cluster/resources", params={"type": "vm"})
    resp.raise_for_status()
    guests = []
    for resource in resp.json()["data"]:
        if resource.get("template") == 1:
            continue
        vmid, node, gtype, name = resource["vmid"], resource["node"], resource["type"], resource["name"]
        nics = []
        try:
            config_resp = client.get(f"/api2/json/nodes/{node}/{gtype}/{vmid}/config")
            config_resp.raise_for_status()
            config = config_resp.json()["data"]
        except httpx.HTTPError:
            config = None
        if config is not None:
            agent_macs = {}
            if gtype == "qemu":
                try:
                    agent_resp = client.get(f"/api2/json/nodes/{node}/qemu/{vmid}/agent/network-get-interfaces")
                    agent_resp.raise_for_status()
                    agent_macs = parse_agent(agent_resp.json())
                except httpx.HTTPError:
                    agent_macs = {}
            for key, value in config.items():
                if not NIC_KEY_RE.match(key):
                    continue
                parsed = parse_net(value)
                mac = parsed["mac"]
                ips = agent_macs.get(mac, [parsed["ip"]] if parsed["ip"] else [])
                nics.append({"name": key, "mac": mac, "ips": ips})
        guests.append({"name": name, "vmid": vmid, "node": node, "type": gtype, "nics": nics})
    return unique_guest_names(guests)


def make_client(url: str, token_id: str, token_secret: str, verify: bool) -> httpx.Client:
    """Build an httpx.Client authenticated against the Proxmox API with a 10s timeout."""
    return httpx.Client(
        base_url=url,
        headers={"Authorization": f"PVEAPIToken={token_id}={token_secret}"},
        verify=verify,
        timeout=10.0,
    )
