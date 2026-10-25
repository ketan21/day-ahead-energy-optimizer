# Troubleshooting the engine connection

## "Cannot reach the engine: Request failed (404)"

The integration reached a web server, but `/api/v1/config` does not exist there. The
most common causes:

1. **You entered the HA ingress URL.** The integration needs the engine's direct API
   URL, not the sidebar/ingress URL. Use:

   ```text
   http://homeassistant.local:8099
   ```

   Do **not** use `http://homeassistant.local:8123/...`, and do not paste
   `/api/hassio_ingress/...` into the integration.
2. **You are pointing at the legacy add-on.** The legacy add-on (`day_ahead_opt`,
   port 5000, old web UI) has no `/api/v1` routes. The new engine is the separate
   **DAEO Engine** add-on (`daeo`, port 8099).
3. **The new add-on image is not installed/running.** The add-on image must be
   published (see `addon/README.md`) and the add-on must show as started. If the
   container is not running, the error is usually "cannot connect", but a proxy or
   another service on the port can produce 404.
4. **You entered a path instead of a base URL.** Enter only scheme + host + port:

   ```text
   http://homeassistant.local:8099
   ```

   The integration appends `/api/v1/...` itself.

## "The API token is missing or invalid"

The token is the **DAEO engine token**, not a Home Assistant long-lived token.

- Add-on: open the add-on log and copy the line:

  ```text
  DAO API token: ...
  ```

  or from the HA host terminal:

  ```bash
  docker exec addon_local_daeo cat /data/api_token
  ```

  (Use `docker ps` to find the actual container name.)
- Standalone Docker:

  ```bash
  docker compose exec daeo cat /data/api_token
  ```

- If the `/data` volume was deleted/recreated, the token changed. Delete the DAEO
  integration entry and add it again with the new token.
- The HACS integration stores the token at creation. There is no token edit field in
  the options flow yet; delete and re-add the entry.
- The integration requires the latest release (2.1.5), which validates the token
  against `/api/v1/config`. An older build may accept a wrong token and fail later.

## Settings page does not load in HA ingress

The engine UI now uses relative paths and a `<base>` tag so it works under
`/api/hassio_ingress/...` as well as directly. The installed add-on image must be
**2.1.5 or newer**; older images use absolute `/api/v1` and `/static` paths and break
under ingress.

If it still fails:

- Rebuild/publish the add-on image and update the add-on.
- Check the browser console for 404s on `/api/v1/config` or `/static/...`.
- Enter the engine token in the UI token field; the settings/config API requires it.
- For a quick check, open the direct URL:

  ```text
  http://homeassistant.local:8099/settings
  ```

## Verify from the HA host

```bash
# Health is public. Expected: {"status":"ok", "demo":false, "auth_required":true}
curl -i http://homeassistant.local:8099/api/v1/health

# Config requires the engine token.
curl -i -H "Authorization: Bearer <DAO_TOKEN>" \
  http://homeassistant.local:8099/api/v1/config
```

- `200` for config means the token and URL are correct.
- `401` means the token is wrong or the add-on was recreated.
- `404` means the URL is not the new engine (ingress/HA/legacy add-on).

## Which add-on is which?

| Add-on | Slug | API | Port |
|---|---|---|---|
| Legacy Day Ahead Optimizer | `day_ahead_opt` | no `/api/v1` | 5000 internal/ingress only |
| New DAEO Engine | `daeo` | `/api/v1` | 8099 host + ingress |

The HACS integration **Day Ahead Energy Optimizer** is the bridge; it is not the
engine and does not contain the planner.

## The engine is running on my Mac, not in HA

Then the HA integration must use the Mac's LAN address, not `homeassistant.local` or
`localhost`:

```text
http://192.168.x.x:8099
```

The Mac must stay awake, Docker must publish 8099, and the HA host must reach it. For
a production setup, run the engine as the HA add-on instead so the Supervisor manages
it and the `homeassistant_config: ro` recorder mount is available.
