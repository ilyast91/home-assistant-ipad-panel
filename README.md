# Home Assistant iPad Panel

A read-only wall dashboard for Home Assistant, designed for an iPad 2 on iOS 9. It shows a clock, selected entity states, and the time of the last successful update. The server renders plain HTML and CSS, and the page refreshes without JavaScript. No Lovelace, HACS, or iPad app required.

> Early version. The same server runs as a Home Assistant OS App or a Docker Compose service. It is designed for iOS 9, but has not been tested on a physical iPad 2 or a real HAOS Supervisor.

## Home Assistant OS

1. Go to **Settings → Apps → App store → ⋮ → Repositories** (called **Add-ons** on older releases) and add `https://github.com/ilyast91/home-assistant-ipad-panel`.
2. Install **iPad Panel**. In its **Network** settings, set the host port for `8090/tcp` to `8090` (or another free port; the port is disabled by default). Start the App in its default demo mode.
3. On the iPad, open `http://<HAOS-LAN-IP>:8090/` in Safari. Use the port you set above. The page does not go through Home Assistant Ingress. If you prefer a hostname other than `homeassistant.local`, add it to `allowed_hosts`.
4. For real data, edit the App configuration (YAML mode example below), save, and restart it. The App uses the Supervisor-provided token; **do not create or enter a separate HA token**.

```yaml
demo: false
title: Home Panel
timezone: Europe/Berlin
refresh_seconds: 15
allowed_hosts:
  - homeassistant.local
entities:
  - id: sensor.living_room_temperature
    label: Living room
  - id: binary_sensor.front_door
    label: Front door
```

The App is built locally by Supervisor on `amd64` or `aarch64`. These are **server** architectures, not the iPad's architecture.

## Home Assistant Container / Docker Compose

```sh
git clone https://github.com/ilyast91/home-assistant-ipad-panel.git
cd home-assistant-ipad-panel
cp .env.example .env
cp panel.example.json panel.json
docker compose up -d --build
```

The example starts in **demo mode**. By default the panel is reachable only at `http://127.0.0.1:8090/` on the Docker host. To open it from the iPad, set `PANEL_BIND_IP` in `.env` to the Docker host's LAN IPv4 address, then run `docker compose up -d` again. Open `http://<Docker-host-LAN-IP>:8090/` on the iPad.

For real data:

1. Set `HA_URL` in `.env` to the **base URL that the panel container can reach**, e.g. `http://192.168.1.10:8123`, without `/api`. `localhost` inside the panel container is not the HA container. If both services share a Docker network, the HA service name also works.
2. Set `HA_TOKEN` to a [long-lived access token](https://www.home-assistant.io/docs/authentication/#long-lived-access-token) from the HA profile. Prefer a separate non-admin user. Do not commit `.env`.
3. Edit `panel.json`: set `"demo": false` and add your entity IDs, e.g. `"entities": [{"id": "sensor.living_room_temperature", "label": "Living room"}]`. Set `timezone` to an IANA name such as `Europe/Berlin`. Apply both files with `docker compose up -d --force-recreate`.

## Use on the iPad

Open the panel in Safari, then use **Share → Add to Home Screen**. In demo mode you should see a clock and three sample values. For a wall panel, check that the page resumes after sleep and after Wi-Fi reconnects. Refresh is every 15 seconds by default (configurable from 5 to 300). A failed poll leaves the previous values visible and marks them as stale. An unknown entity is shown as unavailable; use the exact entity ID from Home Assistant.

**Trusted LAN only.** The panel has no login, and anyone who can reach it can read the entities shown on it. Do not expose the port to the internet; keep it behind a LAN firewall. If connecting by DNS name, put that hostname in `allowed_hosts`, without a scheme or port. IP addresses work without adding them. The HA token is never sent to the iPad. Use HTTPS for the upstream HA URL if it crosses an untrusted network.

## Development

Python 3.12; the application uses only the standard library. Run tests with `python3 -m unittest discover -s tests -v`. Run the demo without Docker with `python3 ipad_panel/panel.py` (listens on all interfaces on port 8090).
