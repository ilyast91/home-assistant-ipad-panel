# Implement first-run fixes

1. Add regressions for six-character passwords, generated password persistence, host defaults, and login with opaque Origin plus form CSRF checks.
2. Implement startup password selection, one-time login forms and host defaults. Shorten health check interval.
3. Update docs and container smoke tests; verify both startup paths, persistence and CI before publishing 0.2.1.
