# Infrahub

A self-hosted [Infrahub](https://docs.infrahub.app) deployment via Docker Compose. `compose.yml` is the upstream OpsMill compose file; secrets and overrides go in `.env`.

## Run it

1. Copy the env file: `cp .env.example .env`
2. Replace every `replace_me` in `.env` (generator commands are in the comments)
3. Start it: `docker compose up -d`
4. Open `http://localhost:8000` and log in as `admin` with `INFRAHUB_INITIAL_ADMIN_PASSWORD`

Upgrade by bumping `VERSION` in `.env`, then `docker compose pull && docker compose up -d`. Any variable from the [configuration reference](https://docs.infrahub.app/reference/configuration) can be set in `.env`.

IPAM (IP prefixes and addresses) is loaded automatically from `schemas/` on every start. See [`schemas/README.md`](schemas/README.md).

SSO (Authentik or any OIDC provider): fill in the commented `SSO via OIDC` block in `.env`. See the [SSO guide](https://docs.infrahub.app/deploy-manage/user-management/sso/configure-sso).

### IPAM sync (Proxmox + network scan)

The `ipam-sync` service keeps IPAM filled in automatically: every 15 minutes it pulls VMs/LXCs from Proxmox VE, scans the LAN with `nmap`, and removes entries it created that are no longer seen. It only ever touches objects it created itself (`managed_by: ipam-sync`); hand-entered IPs, prefixes and devices are never modified. It comes up with the rest of the stack, `PROXMOX_URL` empty just disables the Proxmox half and runs the scan only.

To enable the Proxmox half, create a read-only API token on the Proxmox host:

1. **Datacenter → Permissions → Users**: add user `ipam@pve`.
2. **Datacenter → Permissions → API Tokens**: add token `infrahub` for `ipam@pve`, with "Privilege Separation" checked.
3. **Datacenter → Permissions**: add role `PVEAuditor` on path `/` twice, once as a **User Permission** for `ipam@pve` and once as an **API Token Permission** for `ipam@pve!infrahub`. A privilege-separated token only gets what both it and its user have; with just one of the two, Proxmox returns an empty guest list.
4. In `.env`, set `PROXMOX_URL` to a node's LAN address, not a reverse-proxy hostname (e.g. `https://192.168.1.10:8006`), `PROXMOX_TOKEN_ID` (`ipam@pve!infrahub`) and `PROXMOX_TOKEN_SECRET` to the values above.

To run one sync cycle by hand (useful after changing `.env`, or to check it works):

```bash
docker compose run --rm -e IPAM_SYNC_ONCE=1 ipam-sync
```

This repo is built on a GitHub template for bootstrapping self-hosting projects with linting, CI, and release automation already wired up (documented below).

## What's included

- **`environment.yml` / `requirements.txt`** — conda environment (Python, pip, `gh`) with Python deps installed via pip.
- **`pyproject.toml`** — [tox](https://tox.wiki) environments for linting and formatting:
  - `lint` — `ruff check`
  - `format` — `ruff format` + `ruff check --fix` + `prettier --write` + `taplo fmt`
  - `txt-lint` — [textlint](https://textlint.github.io/) over `**/*.txt`
  - `prettier` — `prettier --check` over CSS/JS/HTML/JSON/YAML/Markdown
  - `toml-lint` — `taplo` format/lint check over TOML files
  - `duplicate-code` — [jscpd](https://github.com/kucherenko/jscpd) zero-tolerance duplicate-code scan (config in `.jscpd.json`). Real duplication should be refactored into a shared file the callers source/import, not waved off by raising the threshold.
  - `github` — the full read-only CI chain (`lint` + `txt-lint` + `prettier` + `toml-lint` + `duplicate-code`)
  - `all` — `format` then `github`
  - Also configures [git-cliff](https://git-cliff.org/) for generating changelogs/PR descriptions from Conventional Commits.
- **`package.json`** — `prettier` and `textlint` (+ plugins), installed on demand by the relevant tox envs.
- **`scripts/render_env_docs.py`** — renders `*.md.template` files, substituting `${VAR}` / `${VAR:-default}` / `${VAR:?message}` references (same syntax as `compose.yml`) from `.env`. Run it via `tox -e render-docs` or `make render-docs`. Write `docs/setup.md.template`, run the renderer, and it produces `docs/setup.md` with real values filled in. **Don't use this for docs that get committed if `.env` holds secrets** — either keep the rendered output gitignored, or only template non-sensitive values (domain, ports) and leave real secrets out of the template entirely.
- **`.github/workflows/`**
  - `tests.yml` — runs `tox -e github` on every push and PR.
  - `secret-detection.yml` — [TruffleHog](https://github.com/trufflesecurity/trufflehog) scan on every push and PR.
  - `release.yml` — on push to `main`, bumps semver based on Conventional Commit prefixes (`feat` → minor, `fix`/other → patch, `!`/`BREAKING CHANGE` → major) and publishes a GitHub Release with an auto-generated changelog.
- **`CODEOWNERS`** — defaults review ownership to `@Self-Host-Server/code-owners`.
- **`.gitignore`** — editor/AI-assistant artifacts (`.vscode`, `.cursor`, `CLAUDE.md`, etc.), `.env`, `node_modules`.

## Development

1. Set up the environment: `make conda` (creates the `infrahub` conda env and installs node deps)
2. Install `tox` and run the full check locally before pushing:

   ```bash
   pip install tox
   tox -e github   # lint + txt-lint + prettier + toml-lint + duplicate-code
   tox -e format   # auto-fix formatting issues
   ```

## Contributing

See [CONTRIBUTING.md](CONTRIBUTING.md) for the commit convention (Conventional Commits — it drives changelog generation and release versioning) and the local checks to run before opening a PR.
