# IPAM sync: Proxmox + network scan

Status: draft for approval, 2026-11-11

## Why

Infrahub's IPAM only knows the IPs someone types in. The owner wants to answer two questions without manual entry:

1. Which IPs in `192.168.1.0/24` are free, so a new LXC/VM can get one.
2. For a used IP, which VM or LXC owns it.

## Goals

1. Every Proxmox VM and LXC appears in Infrahub with its name, the Proxmox node it runs on, and its IPs.
2. Every live IP on `192.168.1.0/24` appears in Infrahub, linked to its VM/LXC when one matches, otherwise as an unlinked IP.
3. Data stays current with no manual steps: runs every 15 minutes.
4. Stale entries are removed automatically:
   1. A VM/LXC gone from Proxmox is removed on the next run.
   2. An IP not seen by any source for 7 days is removed.

## Non-goals

1. More than one subnet. Only `192.168.1.0/24` for now (config allows a list, but only this one is tested).
2. Port scanning, OS detection, or any service inventory.
3. Writing anything back to Proxmox.
4. Alerting (for example "new unknown device").
5. Tracking VM CPU, memory or disk, even though the schema has fields for them.

## Anti-goals (would count as failure even if it works)

1. **Deleting anything a human entered.** Only objects the sync created may be updated or removed. Hand-added IPs, prefixes, devices are never touched.
2. Needing `qemu-guest-agent` on VMs. It is used when present, never required.
3. Needing a Proxmox token with write access.
4. A separate process or host to run: it must come up with `docker compose up -d`.

## Constraints

1. Runs on `netbox`: a Proxmox LXC, 3 cores, small disk (3.7 GB free). Keep the image addition small.
2. Infrahub 1.11.10, schemas from `schemas/` loaded by the existing `schema-loader` service.
3. Repo conventions: Python, ruff, prettier, jscpd zero-duplication (see `README.md`). Secrets only in `.env`, documented in `.env.example` with `replace_me`.
4. Proxmox is reachable over its HTTPS API on port 8006, likely with a self-signed certificate.

## Decided design

### Runtime

1. One new compose service, `ipam-sync`.
2. Image: built from a short `ipam_sync/Dockerfile` `FROM` the Infrahub image (already pulled, already has `infrahub-sdk` and `httpx`) plus `nmap` from the OS package manager.
3. `network_mode: host`, so nmap sees MAC addresses via ARP on the LAN. Reaches Infrahub at `http://localhost:8000` (already published).
4. Waits for `schema-loader` to complete successfully before starting.
5. Loop: Proxmox sync → network scan → stale cleanup → sleep 15 minutes. A failure in one step is logged; the remaining steps still run and the loop continues.
6. nmap needs raw sockets for ARP: run as root with `cap_add: [NET_RAW, NET_ADMIN]`.

### Configuration (`.env`)

| Variable                     | Meaning                                    | Default           |
| ---------------------------- | ------------------------------------------ | ----------------- |
| `PROXMOX_URL`                | Any node, e.g. `https://192.168.1.10:8006` | empty = scan only |
| `PROXMOX_TOKEN_ID`           | e.g. `ipam@pve!infrahub`                   | empty = scan only |
| `PROXMOX_TOKEN_SECRET`       | token secret                               | empty = scan only |
| `PROXMOX_VERIFY_TLS`         | verify Proxmox certificate                 | `false`           |
| `IPAM_SCAN_SUBNETS`          | comma-separated CIDRs                      | `192.168.1.0/24`  |
| `IPAM_SYNC_INTERVAL_MINUTES` | loop interval                              | `15`              |
| `IPAM_STALE_DAYS`            | days unseen before an IP is removed        | `7`               |

Infrahub token: reuse `INFRAHUB_INITIAL_ADMIN_TOKEN` (same as `schema-loader`).

The README gets the steps to create a read-only Proxmox token (role `PVEAuditor` on `/`, privilege separation on).

### Data model

1. Add OpsMill `extensions/compute/compute.yml` (same commit `26336e9`) to `schemas/`.
2. Proxmox node → a new `ProxmoxNode` (defined in `schemas/ipam_sync.yml`, inherits `VirtualizationHostVirtualMachine`, has a unique `name`). Not OpsMill's `ComputePhysicalServer`: that requires a location, and the base schemas have no concrete location type, so it would force a Region/Country/Metro/Site chain for one homelab.
3. VM or LXC → `VirtualizationVirtualMachine`, named after the guest, `host` = its `ProxmoxNode`. Two guests with the same name: the later one (by VMID) is named `<name>-<vmid>`.
4. Each guest NIC → an `InterfaceVirtual` on the VM (it inherits both `InterfaceLayer2` for the MAC and `InterfaceLayer3` for IPs), named after the Proxmox NIC (`net0`).
5. New file `schemas/ipam_sync.yml`, a schema extension that adds to `IpamIPAddress`:
   1. `mac_address` (optional text)
   2. `last_seen` (optional datetime)
   3. `managed_by` (optional text; set to `ipam-sync` on every object the sync creates)
6. Also add `managed_by` to every other kind the sync creates (VM, interface, prefix; `ProxmoxNode` defines it directly), so the anti-goal above can be enforced by filtering on it.
7. IPs are created inside the `default` IP namespace. The sync also creates the `192.168.1.0/24` prefix if missing (marked `managed_by`), so utilization shows without manual setup; an existing hand-made prefix is left alone.

### Proxmox sync

1. `GET /api2/json/cluster/resources?type=vm`: all VMs and LXCs across the cluster with node and type.
2. Per guest, read its config (`/nodes/{node}/{qemu|lxc}/{vmid}/config`) for `netN` lines: MAC addresses, and for LXCs the static `ip=` value.
3. For VMs, try the guest agent (`/nodes/{node}/qemu/{vmid}/agent/network-get-interfaces`); on any error, continue without IPs.
4. Create or update the node, guest, interfaces, and any IPs found. IPs found here get `last_seen` = now.
5. Guests and nodes with `managed_by=ipam-sync` that are no longer in Proxmox are deleted (with their managed interfaces). **Only when the guest list call succeeded**: an API error or empty response from an unreachable Proxmox must never delete anything.
6. Only IPv4 addresses inside `IPAM_SCAN_SUBNETS` are recorded; loopback, link-local and IPv6 from the guest agent are ignored.
7. A guest whose IP comes from Proxmox (static LXC config or guest agent) gets `last_seen` refreshed every run, even when stopped. So a stopped LXC keeps its IP reserved until the LXC is deleted.

### Network scan

1. `nmap -sn -oX - <subnet>` for each configured subnet; parse IP and MAC from the XML.
2. For each live IP: create it if missing (managed), set `last_seen` = now, set `mac_address` when known.
3. If the MAC matches an interface the Proxmox sync recorded, attach the IP to that interface. This is how VMs without the guest agent get their IPs.
4. A hand-made IP (no `managed_by`) is never modified, even if seen.

### Stale cleanup

1. Delete managed IPs whose `last_seen` is older than `IPAM_STALE_DAYS`.
2. Never delete anything without `managed_by=ipam-sync`.
3. IP addresses are stored with the subnet's prefix length (for example `192.168.1.20/24`), matching how Infrahub files them under the prefix.

## Testing

1. Unit tests (pytest, no network, run by a new `tox -e test` env and added to the `github` chain): parsing of Proxmox `netN` config strings, parsing nmap XML, MAC matching, stale-age decision, and the rule that unmanaged objects are never selected for update or delete.
2. End-to-end, local: full stack with a fake Proxmox (recorded JSON responses) and a real scan of a Docker network; confirm objects appear, a second run changes nothing, and removing a guest from the fake data removes it from Infrahub.
3. On `netbox`: one manual run against the real Proxmox, then check the IPAM view.

## Left to the builder

1. Code layout under `ipam_sync/`, module boundaries, logging format.
2. Retry and timeout values for Proxmox and Infrahub calls.
3. Whether to use Infrahub's SDK `upsert` or manual get/create.
