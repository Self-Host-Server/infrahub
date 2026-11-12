import logging
from datetime import datetime

from infrahub_sdk.client import InfrahubClientSync
from infrahub_sdk.exceptions import Error as InfrahubError

from ipam_sync.rules import MANAGED, is_stale, normalize_mac, plan_ip_write, select_deletions, to_cidr

log = logging.getLogger(__name__)


def _first(client: InfrahubClientSync, kind: str, **filters):
    """Return the first node matching the filters, or None."""
    results = client.filters(kind=kind, **filters)
    return results[0] if results else None


def _managed(client: InfrahubClientSync, kind: str) -> list[dict]:
    """List {"name", "managed_by"} for every node of kind managed by ipam-sync."""
    return [{"name": n.name.value, "managed_by": n.managed_by.value} for n in client.filters(kind=kind, managed_by__value=MANAGED)]


def _hand_made(client: InfrahubClientSync, kind: str, name: str) -> bool:
    """True if a node of kind with this name exists and was not created by ipam-sync (upsert would take it over)."""
    existing = _first(client, kind, name__value=name)
    return existing is not None and existing.managed_by.value != MANAGED


def _ensure_prefix(client: InfrahubClientSync, subnet: str) -> None:
    """Create the managed IpamPrefix for subnet if no prefix (managed or hand-made) exists yet."""
    if client.filters(kind="IpamPrefix", prefix__value=subnet):
        return
    prefix = client.create(kind="IpamPrefix", data={"prefix": subnet, "managed_by": MANAGED})
    prefix.save(allow_upsert=True)


def _upsert_ip(client: InfrahubClientSync, cidr: str, now: datetime, mac: str | None, interface_id: str | None):
    """Create or refresh a managed IpamIPAddress, never touching a hand-made one. Returns the node, or None if skipped."""
    existing = _first(client, "IpamIPAddress", address__value=cidr)
    action = plan_ip_write(existing.managed_by.value if existing else None, existing is not None)
    if action == "skip":
        return None
    data = {"address": cidr, "managed_by": MANAGED, "last_seen": now.isoformat()}
    if mac:
        data["mac_address"] = mac
    if interface_id:
        data["interface"] = interface_id
    node = client.create(kind="IpamIPAddress", data=data)
    node.save(allow_upsert=True)
    return node


def _set_primary(client: InfrahubClientSync, vm_id: str, ip_id: str) -> None:
    """Show the IP on the VM's page by making it the VM's primary address (managed VMs only)."""
    # shortcut: a VM with several IPs shows the last one linked; pick by role/interface if that matters
    vm = client.get(kind="VirtualizationVirtualMachine", id=vm_id)
    if vm.managed_by.value == MANAGED and vm.primary_address.id != ip_id:
        vm.primary_address = ip_id
        vm.save()


def _delete_missing(client: InfrahubClientSync, kind: str, keep_names: set[str]) -> None:
    """Delete managed nodes of kind not in keep_names. VM deletions also remove their managed interfaces."""
    for item in select_deletions(_managed(client, kind), keep_names):
        node = _first(client, kind, name__value=item["name"])
        if node is None:
            continue
        if kind == "VirtualizationVirtualMachine":
            for iface in client.filters(kind="InterfaceVirtual", managed_by__value=MANAGED, device__ids=[node.id]):
                client.delete(kind="InterfaceVirtual", id=iface.id)
        client.delete(kind=kind, id=node.id)


def sync_guests(client: InfrahubClientSync, guests: list[dict], subnets: list[str], now: datetime) -> None:
    """Upsert Proxmox nodes/guests/interfaces/IPs, then delete managed ones no longer in Proxmox."""
    for subnet in subnets:
        _ensure_prefix(client, subnet)

    nodes = {}
    keep_vm_names = set()
    for guest in guests:
        node_name = guest["node"]
        if node_name not in nodes:
            if _hand_made(client, "ProxmoxNode", node_name):
                nodes[node_name] = _first(client, "ProxmoxNode", name__value=node_name)
            else:
                proxmox_node = client.create(kind="ProxmoxNode", data={"name": node_name, "managed_by": MANAGED})
                proxmox_node.save(allow_upsert=True)
                nodes[node_name] = proxmox_node

        if _hand_made(client, "VirtualizationVirtualMachine", guest["name"]):
            log.warning("skipping guest %r: a hand-made VM already uses this name", guest["name"])
            continue
        vm = client.create(
            kind="VirtualizationVirtualMachine",
            data={"name": guest["name"], "host": nodes[node_name].id, "managed_by": MANAGED},
        )
        try:
            vm.save(allow_upsert=True)
        except InfrahubError:
            log.warning("skipping guest %r: a non-managed device already uses this name", guest["name"])
            continue
        keep_vm_names.add(guest["name"])

        for nic in guest["nics"]:
            iface_data = {"name": nic["name"], "device": vm.id, "status": "active", "managed_by": MANAGED}
            if nic.get("mac"):
                iface_data["mac_address"] = nic["mac"]
            iface = client.create(kind="InterfaceVirtual", data=iface_data)
            iface.save(allow_upsert=True)

            for ip in nic.get("ips", []):
                cidr = to_cidr(ip, subnets)
                ip_node = _upsert_ip(client, cidr, now, mac=nic.get("mac"), interface_id=iface.id) if cidr else None
                if ip_node:
                    _set_primary(client, vm.id, ip_node.id)

    _delete_missing(client, "VirtualizationVirtualMachine", keep_vm_names)
    _delete_missing(client, "ProxmoxNode", set(nodes))


def record_scan(client: InfrahubClientSync, hits: list[dict], subnets: list[str], now: datetime) -> None:
    """Record live hosts found by the network scan, linking to a managed interface when the MAC matches."""
    # Infrahub stores interface MACs uppercase and filters case-sensitively, so match in Python instead.
    iface_by_mac = {
        normalize_mac(i.mac_address.value): (i.id, i.device.id) for i in client.filters(kind="InterfaceVirtual", managed_by__value=MANAGED) if i.mac_address.value
    }
    for hit in hits:
        cidr = to_cidr(hit["ip"], subnets)
        if cidr is None:
            continue
        mac = hit.get("mac")
        iface_id, vm_id = iface_by_mac.get(mac, (None, None))
        ip_node = _upsert_ip(client, cidr, now, mac=mac, interface_id=iface_id)
        if ip_node and vm_id:
            _set_primary(client, vm_id, ip_node.id)


def delete_stale(client: InfrahubClientSync, now: datetime, days: int) -> int:
    """Delete managed IPs whose last_seen is older than days. Returns the number deleted."""
    deleted = 0
    for ip in client.filters(kind="IpamIPAddress", managed_by__value=MANAGED):
        last_seen = datetime.fromisoformat(ip.last_seen.value) if ip.last_seen.value else None
        if is_stale(last_seen, now, days):
            client.delete(kind="IpamIPAddress", id=ip.id)
            deleted += 1
    return deleted
