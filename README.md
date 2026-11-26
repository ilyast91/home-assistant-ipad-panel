# Home Assistant iPad Panel

A password-protected wall dashboard for Home Assistant, designed for an iPad 2 on iOS 9. It shows a clock, optional weather, and a customizable widget grid. Tap the whole light or switch tile to toggle it. The server renders plain HTML and CSS, with small ES5 scripts for live updates and the visual editor. No Lovelace, HACS, or native app required.

> The two launch paths are tested against a simulated Home Assistant. A physical iPad 2 and a real HAOS installation still need testing.

## Home Assistant OS

1. In Home Assistant, open **Settings → Apps → App store → ⋮ → Repositories** (**Add-ons** on older releases). Add `https://github.com/ilyast91/home-assistant-ipad-panel` and install **iPad Panel**.
2. Start the App in demo mode. Open its **Log** tab and copy the first-start `Generated panel password` value. Alternatively, set `panel_password` in **Configuration** to your own password (at least 6 characters) and restart.
3. Click **Open Web UI** or open **`http://<HAOS-LAN-IP>:8090/`** in Safari. Port **8090** is enabled on new installations. If the link times out after an upgrade, open the App's **Network** tab, enter `8090` next to `8090/tcp`, save and restart. If `8090` is in use, choose a free host port and use it in the URL.
4. For your own devices, set `demo: false`, save, and restart. The App uses the Supervisor-provided token, so no separate HA token is required. In the panel, sign in and open **Settings** to add devices.

Use the panel URL directly, not HA Ingress. Hostnames are unrestricted when `allowed_hosts: []`. To keep a hostname allowlist, enter names explicitly. Existing installations with a saved list keep that list until you clear it. App builds are available on `amd64` and `aarch64` servers regardless of the iPad's processor.

## Home Assistant Container / Docker Compose

```sh
git clone https://github.com/ilyast91/home-assistant-ipad-panel.git
cd home-assistant-ipad-panel
cp .env.example .env
cp panel.example.json panel.json
```

1. Leave `PANEL_PASSWORD` empty to generate a password or set your own (6+ characters) in `.env`. The example publishes port `8090` on the LAN. For tighter binding set `PANEL_BIND_IP` to the Docker host's LAN address, or `127.0.0.1` for local testing only. An existing `.env` may still use `127.0.0.1`; change it if the iPad cannot connect.
2. Run `docker compose up -d --build`. If you did not set a password, find `Generated panel password` in `docker compose logs ipad-panel`. Open **`http://<Docker-host-LAN-IP>:8090/`** on the iPad and sign in. The example starts in demo mode.
3. For real devices, set `HA_URL` (the base URL **reachable from the panel container**, e.g. `http://192.168.1.10:8123`, without `/api`) and `HA_TOKEN` (a [long-lived access token](https://www.home-assistant.io/docs/authentication/#long-lived-access-token) from a separate non-admin HA user when possible). Set `"demo": false` in `panel.json`, then run `docker compose up -d --force-recreate`.

`localhost` inside the panel container is not the HA container. If both containers share an explicit Docker network, you can use the HA service name instead. The dashboard selection lives in the `panel-data` volume; do not remove it with `docker compose down -v` unless you want to reset the saved selection.

## Add and control devices

- Go to **Settings → Add a widget**. Search by name or entity ID, filter by type, and pick an item to preview and name it. Results show which devices are already on the panel. Add up to 24 widgets.
- Select a tile to rename or resize it (**1 × 1** or **2 × 1**). Drag its **Move** handle by touch, tap a free cell, or use the arrows. Use **Save layout** to apply changes, or **Cancel** to discard the draft. Existing tiles migrate automatically.
- In **Settings**, choose **Light** or **Dark**; theme changes save immediately. Under **Weather next to the clock**, the default **Automatic — Home Assistant** detects a `weather.*` entity and shows current temperature and conditions. You can choose another entity or hide the card. Weather changes save with the layout.
- Tap anywhere on a `light.*` or `switch.*` tile. The tile keeps its last confirmed state until HA reports the change; pending or failed requests appear below the tile. Unavailable or stale controls cannot be pressed. Demo controls only simulate changes.
- Under **Settings → Time zone**, use the Home Assistant time zone or search for a city/region and select a manual zone. This applies to the clock and the last update time; downtime does not erase the last detected zone. Existing deployment time zones are preserved until you override them here.
- If JavaScript is disabled, the dashboard still refreshes and can submit control forms; the visual editor links to basic device settings. Use **Share → Add to Home Screen** in Safari if desired. The last successful update is shown with its date and time; it stays unchanged during a connection outage.

## Network and password

An automatically generated password is logged only the first time it is created and kept in the App data directory or the Compose `panel-data` volume. Do not share the log line. If you lose the password, set your own in App configuration or `.env` and restart or recreate the container; no device settings need to be reset. Sign-in sessions last up to seven days and are cleared when the panel restarts. The HA token stays on the server. **Plain HTTP is for a trusted LAN only**: it does not encrypt either the password or the session. Do not forward the port to the internet. `secure_cookie` defaults to `false` in both HAOS and Compose so login works over direct HTTP. An existing `true` setting is preserved on upgrades: switch it to `false` and restart if you use an `http://` URL. Enable it only if you serve the panel through a trusted HTTPS reverse proxy, and preserve the original `Host` header. Do not reuse your HA password as the panel password.

## Development

Python 3.12, standard library only. Run `python3 -m unittest discover -s tests -v` for unit tests, or `./tests/smoke-docker.sh` to build and check both launch paths against a simulated HA instance. GitHub Actions builds and smoke-tests the image on native `linux/amd64` and `linux/arm64` runners. To test an image already in the local daemon, run `./tests/smoke-docker.sh <image:tag>`. A standalone local demo can be started with `PANEL_PASSWORD='your-test-password' python3 ipad_panel/panel.py` (listens on all interfaces on port 8090).
