# Faster first run and login compatibility

- Run the container health check every few seconds against the unauthenticated liveness route, without waiting on HA.
- Authenticate login submissions with a one-time token tied to a pre-login HttpOnly cookie. Allow missing or opaque Origin values; retain origin checks for explicit cross-site origins as well as CSRF for protected POSTs. Empty allowed_hosts permits all syntactically valid hosts (explicit configured names remain supported).
- Manual passwords may be 6–256 characters. If no manual password is set, generate a strong random password, persist it in the existing state directory with owner-only permissions, and log it only on first creation. Manual configuration overrides the generated secret. Existing state and manual credentials are preserved.
