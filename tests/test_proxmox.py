import json
from pathlib import Path

import httpx
import pytest

from ipam_sync.proxmox import fetch_guests, parse_net

FIXTURES = json.loads((Path(__file__).parent / "fixtures" / "proxmox.json").read_text())


def _mock_handler(request: httpx.Request) -> httpx.Response:
    body = FIXTURES.get(request.url.path)
    if body is None:
        return httpx.Response(500)
    return httpx.Response(200, json=body)


def _failing_handler(request: httpx.Request) -> httpx.Response:
    return httpx.Response(500)


@pytest.fixture
def mock_client():
    return httpx.Client(transport=httpx.MockTransport(_mock_handler), base_url="https://proxmox.example.com")


@pytest.fixture
def failing_client():
    return httpx.Client(transport=httpx.MockTransport(_failing_handler), base_url="https://proxmox.example.com")


def test_parse_net_vm():
    assert parse_net("virtio=BC:24:11:AA:BB:CC,bridge=vmbr0,firewall=1") == {"mac": "bc:24:11:aa:bb:cc", "ip": None}


def test_parse_net_lxc_static():
    assert parse_net("name=eth0,bridge=vmbr0,hwaddr=BC:24:11:00:00:01,ip=192.168.1.53/24,gw=192.168.1.1")["ip"] == "192.168.1.53/24"


def test_parse_net_lxc_dhcp():
    assert parse_net("name=eth0,hwaddr=BC:24:11:00:00:02,ip=dhcp")["ip"] is None


def test_fetch_guests(mock_client):
    guests = {g["name"]: g for g in fetch_guests(mock_client)}
    assert set(guests) == {"dns", "web", "old", "broken"}  # template skipped
    assert guests["dns"]["nics"][0]["ips"] == ["192.168.1.53/24"]
    assert "192.168.1.80" in guests["web"]["nics"][0]["ips"]
    assert guests["old"]["nics"][0]["ips"] == [] and guests["old"]["nics"][0]["mac"]  # agent 500 -> MAC kept
    assert guests["broken"]["nics"] == []  # config 500 -> still listed


def test_fetch_guests_list_failure_raises(failing_client):
    with pytest.raises(httpx.HTTPError):
        fetch_guests(failing_client)
