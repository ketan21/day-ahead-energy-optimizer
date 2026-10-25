# DAEO Engine add-on

The engine add-on runs the CBC planner, the FastAPI service, the web UI, and the
SQLite plan store. The Home Assistant integration is a separate HACS artifact.

## Image

The add-on pulls:

```text
ghcr.io/ketan21/daeo:2.1.0
```

The version tag must match `version` in `addon/config.yaml`. The image is built by
`.github/workflows/daeo-image.yml` for `linux/amd64` and `linux/arm64`.

### Publish

1. Keep `addon/config.yaml` `version` and the workflow input/default in sync.
2. Tag the repository:

```bash
git tag v2.1.0
git push origin v2.1.0
```

or run the **DAEO add-on image** workflow manually with `version: 2.1.0`.
3. Make the GHCR package **public**:
   GitHub → your profile → Packages → `daeo` → Package settings → Change visibility.

If the package is private, the Supervisor cannot pull it without registry
credentials.

### Build locally

```bash
docker build -f addon/Dockerfile -t ghcr.io/ketan21/daeo:2.1.0 .
```

The build context is the repository root.

## Runtime

- Ingress only, port 8099 internally; no host port is published.
- `/data` holds the SQLite database, API token, and optional secrets.
- `homeassistant_config: ro` makes the HA recorder available at
  `/homeassistant/home-assistant_v2.db` for load profiles.
- `demo_mode: false` (default) requires the API token and exposes port 8099 to the
  LAN for the integration. The token is printed in the add-on log and stored in
  `/data/api_token` (mode 0600). Use `demo_mode: true` only for an isolated demo; it
  disables API auth.

## Pairing with the HA integration

1. Install the HACS integration from `custom_components/daeo`.
2. Read the engine token:
   - Add-on: `docker exec addon_local_daeo cat /data/api_token` (adjust the
     container name from `docker ps`)
   - Standalone: `docker compose exec daeo cat /data/api_token`
3. Add the integration and enter the engine URL and token.

The add-on UI does not display the token yet; use the terminal path above.

## Control

The add-on plans and serves the plan. The HACS integration owns HA entity I/O and
the battery control loop. Keep `switch.daeo_battery_control` off until the
integration and entity mapping are verified.
