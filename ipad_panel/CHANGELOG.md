# Changelog

## 0.3.0

- Redesigned dashboard with light/dark themes, full-tile controls, weather, and a visible last-success timestamp.
- On-device four-column editor with touch handles, keyboard alternatives, and two tile sizes.
- Searchable widget catalogue with type filters, preview, and draft layout changes.

## 0.2.1

- Check container readiness within a few seconds, without waiting for HA data.
- Support sign-in from legacy Safari with an opaque or missing Origin while keeping one-time form protection.
- Accept all hostnames by default; allow an explicit hostname list.
- Accept custom passwords from six characters, or generate and save a password on first start.

## 0.2.0

- Publish HAOS port 8090 by default for new installs; existing installs may retain their previous Network override.
- Require a panel password for dashboard, settings, and controls.
- Find, add, rename, or remove Home Assistant entities in Settings. Existing configured tiles are imported once.
- Control selected lights and switches using explicit On and Off actions.

## 0.1.0

Initial read-only dashboard: demo mode, HA REST polling, stale-data status, and a JavaScript-free interface.
