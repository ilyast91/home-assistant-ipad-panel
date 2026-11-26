# Panel setup and controls

- HAOS publishes port 8090 on new installations. A previously stored port override may need to be changed through the Network tab once. Compose documents its bind address in the example immediately. Both show a setup-only page when a password is missing.
- Require a panel password for every page with device data and every write. Use a time-limited HTTP-only session cookie and a separate CSRF token for authenticated forms; do not send the HA credential to the browser. Support Secure cookies when served over HTTPS. Keep plain HTTP LAN-only.
- A non-refreshing settings page searches the HA state catalogue on demand, with friendly names and entity IDs. Add with a custom label, rename or remove. Store changes atomically in an application state directory. Import legacy HAOS/Compose config entities once if no selection has been saved. Do not require configured entities for live startup.
- On the dashboard expose only explicit turn_on/turn_off for a selected light or switch. No arbitrary service endpoints, other domains or controls in demo mode. Keep the UI HTML/CSS only.
