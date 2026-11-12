# Schemas

Loaded into Infrahub by the `schema-loader` service in `compose.yml` on every `docker compose up`. Loading an unchanged schema is a no-op.

The `base/` files from [opsmill/schema-library](https://github.com/opsmill/schema-library/tree/26336e9026dff1907f2c58e81dd6ae7b5c3f763e/base) at commit `26336e9` (Apache-2.0). `ipam.yml` adds IP prefixes and addresses; it depends on the other three. `compute.yml` is the [`extensions/compute`](https://github.com/opsmill/schema-library/tree/26336e9026dff1907f2c58e81dd6ae7b5c3f763e/extensions/compute) extension from the same repo, same commit.

`ipam_sync.yml` is ours, not from opsmill/schema-library. It adds the `ProxmoxNode` kind and the `managed_by`/`mac_address`/`last_seen` attributes ipam-sync uses to track where IPAM data came from.

To reload by hand: `docker compose run --rm schema-loader`
