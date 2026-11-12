from datetime import datetime, timedelta, UTC

from ipam_sync.rules import (
    MANAGED,
    is_stale,
    normalize_mac,
    plan_ip_write,
    select_deletions,
    to_cidr,
    unique_guest_names,
)


def test_managed_constant():
    assert MANAGED == "ipam-sync"


def test_normalize_mac():
    assert normalize_mac("BC:24:11:AA:BB:CC") == "bc:24:11:aa:bb:cc"
    assert normalize_mac(None) is None


def test_to_cidr():
    s = ["192.168.1.0/24"]
    assert to_cidr("192.168.1.20", s) == "192.168.1.20/24"
    assert to_cidr("192.168.1.20/16", s) == "192.168.1.20/24"
    assert to_cidr("10.0.0.5", s) is None
    assert to_cidr("127.0.0.1", s) is None
    assert to_cidr("fe80::1", s) is None


def test_is_stale():
    now = datetime(2026, 11, 11, tzinfo=UTC)
    assert is_stale(now - timedelta(days=8), now, 7)
    assert not is_stale(now - timedelta(days=6), now, 7)
    assert is_stale(None, now, 7)


def test_plan_ip_write_never_touches_hand_made():
    assert plan_ip_write(None, exists=True) == "skip"
    assert plan_ip_write("ipam-sync", exists=True) == "update"
    assert plan_ip_write(None, exists=False) == "create"


def test_select_deletions_only_managed():
    existing = [{"name": "a", "managed_by": "ipam-sync"}, {"name": "b", "managed_by": None}, {"name": "c", "managed_by": "ipam-sync"}]
    assert [e["name"] for e in select_deletions(existing, {"c"})] == ["a"]


def test_unique_guest_names():
    out = unique_guest_names([{"name": "web", "vmid": 105}, {"name": "web", "vmid": 101}])
    assert [g["name"] for g in out] == ["web", "web-105"]
