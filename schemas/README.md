# Schemas

Loaded into Infrahub by the `schema-loader` service in `compose.yml` on every `docker compose up`. Loading an unchanged schema is a no-op.

The `base/` files from [opsmill/schema-library](https://github.com/opsmill/schema-library/tree/26336e9026dff1907f2c58e81dd6ae7b5c3f763e/base) at commit `26336e9` (Apache-2.0). `ipam.yml` adds IP prefixes and addresses; it depends on the other three.

To reload by hand: `docker compose run --rm schema-loader`
