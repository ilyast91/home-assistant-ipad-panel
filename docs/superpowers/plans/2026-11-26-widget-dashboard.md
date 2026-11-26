# Implement the widget dashboard redesign

1. Add red tests for layout migration, collisions, atomic persistence, theme and weather preferences, and authenticated layout writes. Extend `ipad_panel/selection.py` without breaking existing selections.
2. Add red tests for confirmed control, pending and failed commands, safe fallback forms, weather and last-success timestamp. Extend `ipad_panel/panel.py` and `ipad_panel/web.py` with status reads and bounded readback on command. Retain the existing authentication, CSRF, port and legacy routes.
3. Build the dashboard and editor with legacy-compatible CSS, initial server HTML and a small external ES5 script (`dashboard.js`, `editor.js`). Add touch drags, tap/arrow controls, atomic draft save/cancel, appearance and weather settings, and searchable filtered preview. Test the flows in Chromium and validate ES5 syntax. Add regression tests before changes.
4. Update both installation docs and HAOS version; include assets in the Docker build. Run Python tests, smoke tests against fake HA and both GitHub CI architectures. Publish only after review and report that iOS 9 hardware remains unverified.
