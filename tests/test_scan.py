from pathlib import Path

from ipam_sync.scan import parse_nmap

FIXTURES = Path(__file__).parent / "fixtures"


def test_parse_nmap():
    hits = parse_nmap((FIXTURES / "nmap.xml").read_text())
    assert {"ip": "192.168.1.80", "mac": "bc:24:11:aa:bb:cc"} in hits
    assert {"ip": "192.168.1.5", "mac": None} in hits
    assert len(hits) == 2
