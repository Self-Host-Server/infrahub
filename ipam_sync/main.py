import logging
import os
import time
from datetime import UTC, datetime

from infrahub_sdk.client import InfrahubClientSync

from ipam_sync.proxmox import fetch_guests, make_client
from ipam_sync.scan import run_scan
from ipam_sync.store import delete_stale, record_scan, sync_guests

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
log = logging.getLogger(__name__)


def run_once(config: dict) -> None:
    """Run one Proxmox sync + network scan + stale cleanup cycle. Each step logs and continues on failure."""
    client = InfrahubClientSync(address=config["infrahub_address"], config={"api_token": config["infrahub_api_token"]})
    now = datetime.now(UTC)
    subnets = config["subnets"]

    if not config["proxmox_url"]:
        log.info("PROXMOX_URL is empty, skipping Proxmox sync")
    else:
        try:
            with make_client(config["proxmox_url"], config["proxmox_token_id"], config["proxmox_token_secret"], config["proxmox_verify_tls"]) as proxmox_client:
                guests = fetch_guests(proxmox_client)
            if guests:
                sync_guests(client, guests, subnets, now)
            else:
                # Proxmox returns an empty list (not an error) when the token lacks permissions; never treat that as "all guests deleted".
                log.warning("Proxmox returned no guests; check the API token has PVEAuditor on / — skipping Proxmox sync")
        except Exception:
            log.exception("Proxmox sync failed")

    try:
        hits = run_scan(subnets)
        record_scan(client, hits, subnets, now)
    except Exception:
        log.exception("network scan failed")

    try:
        deleted = delete_stale(client, now, config["stale_days"])
        log.info("stale cleanup: deleted %d IP(s)", deleted)
    except Exception:
        log.exception("stale cleanup failed")


def _config_from_env() -> dict:
    return {
        "infrahub_address": os.environ.get("INFRAHUB_ADDRESS", "http://localhost:8000"),
        "infrahub_api_token": os.environ.get("INFRAHUB_API_TOKEN", ""),
        "proxmox_url": os.environ.get("PROXMOX_URL", "").strip(),
        "proxmox_token_id": os.environ.get("PROXMOX_TOKEN_ID", ""),
        "proxmox_token_secret": os.environ.get("PROXMOX_TOKEN_SECRET", ""),
        "proxmox_verify_tls": os.environ.get("PROXMOX_VERIFY_TLS", "false").strip().lower() in ("1", "true", "yes"),
        "subnets": [s.strip() for s in os.environ.get("IPAM_SCAN_SUBNETS", "192.168.1.0/24").split(",") if s.strip()],
        "stale_days": int(os.environ.get("IPAM_STALE_DAYS", "7")),
    }


def main() -> None:
    config = _config_from_env()
    interval_minutes = int(os.environ.get("IPAM_SYNC_INTERVAL_MINUTES", "15"))
    once = os.environ.get("IPAM_SYNC_ONCE") == "1"

    while True:
        run_once(config)
        if once:
            break
        time.sleep(interval_minutes * 60)


if __name__ == "__main__":
    main()
