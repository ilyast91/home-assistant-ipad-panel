# Implement panel setup and controls

1. Add failing tests for locked startup, authentication, CSRF, catalogue selection persistence/import and permitted actions.
2. Extend the HA client, persist the selection and implement HTML forms/routing and session protection. Run all unit and regression tests.
3. Publish the HAOS default port and configure state storage and credentials for both install paths. Document upgrades, LAN/HTTPS and first launch.
4. Test both images against simulated HA including login, device search, saved selection and control. Verify CI, then publish the update.
