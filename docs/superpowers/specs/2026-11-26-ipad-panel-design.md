# Home Assistant iPad Panel

An independent, read-only dashboard for an iPad 2 on iOS 9. One source tree and image serve both Home Assistant OS (as an App) and generic Docker Compose (for Home Assistant Container). The public repository is `ilyast91/home-assistant-ipad-panel`.

- The server renders plain HTML/CSS with large values, a clock, the time of the last successful poll, and a distinct stale/unavailable status. The page refreshes itself without JS. No controls, Lovelace dependencies, or client-side HA credentials.
- A background poller reads only configured entity states through the official REST API. It retains the last successful snapshot when HA is unreachable and retries at the configured interval. Demo mode has no upstream dependency.
- HAOS supplies settings through `/data/options.json` and uses the Supervisor Core proxy with `homeassistant_api: true`. Compose uses a read-only JSON config and a token in a local environment file. Both build from the same Dockerfile. Access is by a dedicated HTTP port, not Ingress. Keep it on a trusted network and do not publish it to the internet; the panel has no login and displays sensor data to anyone who can reach it.
- Automated tests cover settings in both environments, read-only REST behavior, render escaping and stale data. Validate Compose configuration and smoke-test both container startup paths with a local fake HA. Physical iPad 2 and real HAOS Supervisor testing remain manual.
