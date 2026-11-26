# Panel appearance and large climate widget

- Keep the 2×2 climate tile geometry stable and use its space for a header/mode, a prominent current reading, and an expanded target section with large controls. For a dual setpoint put both targets in the tile. Smaller climate sizes stay compact. Keep server confirmation and focus behaviour.
- Introduce eight named, paired light/dark palettes (Sage, Graphite, Ocean, Teal, Indigo, Lavender, Amber, Terracotta). Persist the palette separately from theme and widget draft and default old data to Sage. Render and preview it on the server and in the editor; no CSS custom properties or new browser requirements.
- Move sensor units to the upper-right of their value, with a gap and baseline offset. Keep the reading unbroken.
- Test storage, validation, authentication, touch and keyboard paths, responsive geometry and palette contrast. Run an independent read-only browser review of the actual app before release and address findings; do not claim hardware testing.
