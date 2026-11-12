from datetime import datetime
from ipaddress import IPv4Address, IPv4Network, AddressValueError

MANAGED = "ipam-sync"


def normalize_mac(mac: str | None) -> str | None:
    """Normalize MAC address to lowercase, or return None if input is None."""
    if mac is None:
        return None
    return mac.lower()


def to_cidr(ip: str, subnets: list[str]) -> str | None:
    """
    Convert IP to CIDR notation by checking which subnet it belongs to.

    Accepts IP with or without CIDR notation. Returns "<ip>/<subnet_prefixlen>" if IP
    is inside a subnet, else None. Only handles IPv4.
    """
    # Extract the IP address part (remove any CIDR notation)
    ip_part = ip.split("/")[0]

    try:
        ip_addr = IPv4Address(ip_part)
    except AddressValueError:
        # Not a valid IPv4 address (e.g., IPv6)
        return None

    # Check if IP is in any of the subnets
    for subnet_str in subnets:
        try:
            subnet = IPv4Network(subnet_str, strict=False)
            if ip_addr in subnet:
                return f"{ip_addr}/{subnet.prefixlen}"
        except AddressValueError:
            # Skip invalid subnet notation
            continue

    return None


def is_stale(last_seen: datetime | None, now: datetime, days: int) -> bool:
    """
    Determine if a last_seen timestamp is stale.

    Returns True if last_seen is None or if the time difference exceeds the given days.
    """
    if last_seen is None:
        return True

    time_diff = now - last_seen
    return time_diff.days > days


def plan_ip_write(existing_managed_by: str | None, exists: bool) -> str:
    """
    Determine the action to take for an IP write operation.

    Returns:
    - "skip" if the IP exists but is hand-made (managed_by is None)
    - "update" if the IP exists and is managed by ipam-sync
    - "create" if the IP doesn't exist
    """
    if exists:
        if existing_managed_by is None:
            return "skip"
        return "update"
    return "create"


def select_deletions(existing: list[dict], keep_names: set[str]) -> list[dict]:
    """
    Select items from existing that should be deleted.

    Returns only items where managed_by == "ipam-sync" and name is not in keep_names.
    """
    return [item for item in existing if item.get("managed_by") == MANAGED and item["name"] not in keep_names]


def unique_guest_names(guests: list[dict]) -> list[dict]:
    """
    Ensure unique guest names by renaming duplicates.

    Sorts by vmid, then renames later occurrences of duplicate names to "{name}-{vmid}".
    """
    # Sort by vmid
    sorted_guests = sorted(guests, key=lambda g: g["vmid"])

    # Track seen names and rename duplicates
    seen_names = {}
    result = []

    for guest in sorted_guests:
        name = guest["name"]
        vmid = guest["vmid"]

        if name not in seen_names:
            seen_names[name] = 1
            result.append({**guest, "name": name})
        else:
            # Rename duplicate
            new_name = f"{name}-{vmid}"
            seen_names[name] += 1
            result.append({**guest, "name": new_name})

    return result
