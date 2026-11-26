# Widget dashboard redesign for the iPad 2

## Goal

Turn iPad Panel into a readable, responsive wall dashboard with a layout that can be edited directly in Safari on iOS 9. Keep the same app and behavior on HAOS and Compose. Existing authentication and supported control domains remain unchanged.

## Dashboard

- Use the accepted “Home at a glance” mockup: clock and date on the left, an optional compact weather card opposite, a visible date and time of the last successful HA refresh, and a grid of calm, high-contrast tiles. Match the typography, spacing and contrast of the prototype rather than porting its modern CSS.
- Show current temperature and weather condition from a chosen `weather.*` entity. Without a selection, omit the weather card. Do not fetch forecasts in this release. Distinguish unavailable and stale data from live values; preserve the timestamp during outages.
- Sensor and status tiles are non-interactive. The entire light or switch tile is a single touch/keyboard button. Show confirmed On/Off clearly in both themes, including high-contrast labels on active tiles. An on tap sends explicit `turn_off`; an off tap sends explicit `turn_on`, not a blind toggle. Lock only the pending tile and show progress. Confirm the state from HA, with a bounded wait; on failure retain the last confirmed state and show a retryable error. Disable toggling when the state is unknown or unavailable. Never make a real HA call in demo mode.
- Update data without reloading the page or stealing focus when JavaScript is available. Keep server-rendered content, refresh and form-based actions as the no-JS fallback. Time and date follow the configured panel timezone.

## Layout editor and catalogue

- Use four logical columns on the iPad editor. A tile has an explicit row/column and a size of 1×1 or 2×1. Select a tile, move it with a touch drag from its handle, tap a free cell, or use arrow controls. The latter are also accessible by keyboard. Invalid positions and overlaps are rejected with an inline explanation. Adapt dashboard presentation on small screens without rewriting saved positions.
- Enter a separate editor mode so layout touches cannot control devices. Rename, resize, move, add or remove tiles in a draft. **Save** applies the whole draft; **Cancel** discards it. Persist the layout in the existing application data directory and migrate old selected entities to a deterministic layout without losing their names.
- The add-device catalogue searches friendly name and `entity_id`, filters by type, identifies items already on the panel and previews a tile before it is added. Show the existing result limit/paging, empty and offline states explicitly. Let the user choose the header weather source from discovered weather entities or hide the weather card.
- Appearance settings offer **Light** and **Dark**. Dark is the default. Theme changes apply immediately to the dashboard, editor and add-device catalogue, and persist across reloads and restarts for the panel, independently of the layout draft.

## Implementation constraints

- Use server-rendered HTML, legacy-compatible CSS and an optional small ES5 script. No third-party frontend runtime, CDN, CSS Grid, Pointer Events or modern JavaScript syntax in the application. Use Touch Events with a keyboard/tap fallback, and retain the current authentication and CSRF protections on all writes.
- Extend the persisted selection schema with layout and panel preferences, use atomic writes and server-side validation, and keep tokens server-side. No changes to public API configuration or optional HTTPS behavior. Do not add new equipment control domains.
- Keep the same shared Docker build and test both installation paths on amd64 and arm64. Test persistence/migration, collision validation, catalogue, weather mapping, stale states, control confirmation/failure, form fallback and responsive/keyboard flows. Use an ES5 syntax check and a modern browser run, but do not claim physical iOS 9 support until tested on the device.
