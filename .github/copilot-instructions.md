# GitHub Copilot Instructions — iSeeYou

## Project overview

iSeeYou is a self-hosted infrastructure monitoring and observability platform. It starts with network monitoring for a MikroTik hAP ax3 running RouterOS 7.22 and is designed to expand into system monitoring, service health, logs, alerts and security telemetry.

The project prioritizes:

- Zero mandatory software or subscription costs.
- Self-hosting and local data ownership.
- Security, reliability and maintainability.
- Modular architecture without premature complexity.
- Accurate measurements and transparent error handling.
- Practical Linux administration and infrastructure learning.

## 1. General development rules

- Inspect existing code, configuration and repository conventions before making changes.
- Prefer extending existing abstractions over introducing competing implementations.
- Do not rewrite working components without a clear reason.
- Make small, focused and testable changes.
- Explain significant architectural decisions and their trade-offs.
- Never invent library APIs, configuration options, RouterOS commands or protocol capabilities. Verify them against documentation or existing code.
- Do not use pseudocode or placeholders when implementing a requested feature unless explicitly requested.
- Do not claim functionality is implemented or tested when it is not.
- Do not silently remove existing features, tests or configuration.
- Avoid unnecessary dependencies, frameworks and infrastructure.
- Never introduce paid services, mandatory cloud accounts or external telemetry without explicit approval.
- Ask before performing destructive operations, modifying real infrastructure or changing security-sensitive settings.
- When requirements are ambiguous, state reasonable assumptions and proceed when safe.

## 2. Architecture and modules

Use the `isee[module]` naming convention for functional modules.

Examples:

- `iseeNetwork`
- `iseeSystem`
- `iseeServices`
- `iseeLogs`
- `iseeAlerts`
- `iseeSecurity`

These names represent logical modules and do not imply that every module must be a separate process, package or repository.

Architectural requirements:

- Keep module responsibilities clearly separated.
- Define explicit interfaces between collection, processing, persistence, API and presentation.
- Keep the initial application deployable as a single service.
- Share common configuration, logging, error handling and storage infrastructure.
- Prevent circular dependencies between modules.
- Avoid module-specific copies of shared functionality.
- Do not introduce microservices, Kubernetes, message brokers or distributed infrastructure without a demonstrated need.
- Keep module-specific implementation details out of shared infrastructure.
- Make future modules possible without requiring the existing application to be rewritten.

Use consistent Python package names and filesystem naming conventions. If Python naming conventions require lowercase identifiers, preserve the `iseeNetwork` naming at the conceptual or module-label level while using idiomatic package names such as `isee_network`.

Document significant module interfaces and dependencies.

The Phase 2 RouterOS integration lives in `src/isee_network`. It uses HTTPS REST with certificate verification and GET-only requests; credentials come from `ISEE_ROUTER_PASSWORD`, never TOML. RouterOS REST monitoring users need `read`, `api`, and `rest-api` policies. `isee router discover` is a one-shot diagnostics command, not a polling worker. Do not disable TLS verification or change router configuration from application code.

## 3. Initial technology stack

Prefer the following unless the existing repository or a concrete technical requirement justifies another choice:

- Python for backend and collection logic.
- FastAPI for HTTP endpoints.
- SQLite for initial persistent storage.
- SQLAlchemy or another established persistence layer if its abstraction provides sufficient value.
- Alembic or an appropriate migration mechanism when schema migrations are needed.
- pytest for automated tests.
- TOML or YAML for validated configuration.
- systemd for Linux service management.
- A lightweight web frontend with interactive time-series graphs.

Use asynchronous programming where it materially improves I/O concurrency. Do not introduce `async` everywhere without a reason.

Keep dependencies minimal and document why additional dependencies are necessary.

Do not add Prometheus, Grafana, PostgreSQL, Redis or similar infrastructure by default. Propose such additions only when they solve an identified problem.

## 4. Python coding standards

- Use modern, supported Python syntax and type annotations.
- Follow PEP 8 and standard Python naming conventions.
- Prefer clear, descriptive names over abbreviations.
- Keep functions focused and reasonably small.
- Use structured data models for configuration and API responses where appropriate.
- Avoid broad exception handling that hides failures.
- Catch expected exceptions at appropriate boundaries and preserve useful diagnostic context.
- Do not use mutable default arguments.
- Avoid global mutable state.
- Use context managers for managed resources.
- Ensure network clients, database connections and background tasks have defined lifecycles.
- Use timezone-aware UTC timestamps internally for persisted events and measurements.
- Convert timestamps to local time only for display.
- Use `Decimal` where decimal precision is important; do not introduce it unnecessarily for ordinary telemetry.
- Document non-obvious calculations and protocol-specific behavior.
- Use a formatter and linter such as Ruff if the project adopts them; keep configuration consistent.

## 5. Network monitoring requirements

The first module is `iseeNetwork`.

Target environment:

- MikroTik hAP ax3.
- RouterOS 7.22.
- EndeavourOS development workstation.
- NetworkManager-managed Linux networking.

Collection code must:

- Use documented RouterOS API or SNMP capabilities.
- Prefer read-only access to router data.
- Apply connection and operation timeouts.
- Handle router unavailability and reconnect safely.
- Avoid unbounded retries and aggressive polling.
- Keep collection failures separate from valid measurements.
- Record when a measurement was collected and whether it is valid.
- Expose collector health and data freshness.
- Support configurable polling intervals and targets.
- Avoid changing router configuration automatically.

For interface counters:

- Identify interfaces using stable identifiers when available.
- Calculate throughput from counter deltas and elapsed time.
- Handle initial samples, counter resets, reboots, wraparound and interface replacement.
- Reject invalid or negative deltas instead of generating misleading rates.
- Clearly distinguish bits per second, bytes per second and cumulative byte counts.
- Preserve enough information to diagnose unexpected results.
- Document any limitations caused by RouterOS behavior, hardware offloading or FastTrack.

For connectivity:

- Monitor the local gateway and configurable external targets independently.
- Distinguish failed probes from confirmed outages.
- Account for packet loss, timeouts, DNS failures and stale measurements.
- Avoid relying on a single ICMP destination to determine internet availability.
- Ensure failed collection does not appear as zero latency, zero traffic or a healthy state.

Do not assume per-device traffic attribution is available from interface counters alone. Implement it only through a documented and appropriate data source.

## 6. Data storage and migrations

- Store persistent monitoring measurements and events in the database.
- Use explicit schemas and constraints.
- Include timestamps and relevant device, interface or target identifiers.
- Distinguish missing, stale, invalid and zero-valued measurements.
- Use transactions for related database changes.
- Handle database failures without silently discarding data.
- Design indexes around actual query patterns.
- Use migrations for changes to existing persistent schemas.
- Never delete or reinterpret historical data as part of an ordinary code upgrade without explicit justification.
- Make retention policies configurable.
- Provide documented backup and restore procedures.
- Test behavior across application restarts and database upgrades.

Avoid storing high-cardinality or redundant data without a clear use case.

## 7. API and frontend

API requirements:

- Use explicit request and response schemas.
- Validate input and configuration.
- Return meaningful HTTP status codes and actionable errors.
- Do not expose credentials, internal stack traces or sensitive configuration.
- Keep monitoring collection independent of interactive dashboard requests.
- Ensure a slow or unavailable router does not block unrelated API requests.
- Add pagination or time-range limits to potentially large historical queries.

Frontend requirements:

- Display timestamps, units and data freshness clearly.
- Distinguish healthy, degraded, unavailable and unknown states.
- Do not display missing data as zero.
- Label interface names and measurement units consistently.
- Support historical time ranges without loading excessive amounts of data.
- Handle empty datasets and partial failures gracefully.
- Avoid unnecessary polling and expensive rendering.
- Keep UI components reusable without creating abstractions that have no practical use.

## 8. Security

Treat the router, monitoring database, credentials and dashboard as security-sensitive.

- Never commit credentials, tokens, private keys or real configuration secrets.
- Provide example configuration using placeholders.
- Read secrets from environment variables or appropriately permissioned secret files.
- Do not log passwords, tokens or authentication headers.
- Bind development servers to localhost by default.
- Do not expose the dashboard to the public internet by default.
- Use least-privilege credentials for RouterOS.
- Restrict management protocols to trusted hosts or networks.
- Prefer SNMPv3 with authentication and privacy when SNMP is used and supported by the collector.
- If the RouterOS API is used, prefer a secure transport and explicitly restrict access.
- Validate user-supplied hostnames, IP addresses, ports and configuration values.
- Protect against command injection, SQL injection, path traversal and unsafe deserialization.
- Do not use shell commands with interpolated user input when a library or argument-list subprocess invocation is appropriate.
- Do not disable TLS verification to work around connection errors.
- Do not make firewall, routing or router configuration changes without explicit approval.

Document all network listeners and the intended trust boundaries.

## 9. Reliability and operations

- Support clean startup and shutdown.
- Handle termination signals without corrupting data.
- Prevent duplicate collection workers from starting unintentionally.
- Ensure background tasks have defined cancellation and restart behavior.
- Implement bounded retries with backoff where appropriate.
- Use structured logs with useful context.
- Keep routine status messages separate from errors.
- Provide health endpoints that distinguish application health from upstream device health.
- Avoid reporting the whole application as healthy when collection has silently stopped.
- Ensure the service can restart after a crash or reboot.
- Do not require a graphical desktop session for the monitoring service.
- Keep deployment compatible with a headless Linux host.

The application must remain useful even when the monitored router or internet connection is unavailable.

## 10. Testing requirements

Write automated tests for new behavior and regressions.

Prioritize tests for:

- Throughput calculations and unit conversions.
- Counter resets and invalid samples.
- Polling timeouts and router unavailability.
- Missing or stale measurements.
- Database persistence and migrations.
- Retention policies.
- Configuration validation.
- API response schemas and error handling.
- Alert transitions and duplicate suppression.
- Service startup and shutdown where practical.

Use mocks or recorded fixtures for routine tests. Unit tests must not require access to the real MikroTik, the internet or external services.

Keep hardware-dependent integration tests separate and clearly document their requirements.

Before finishing a change:

1. Run the relevant tests.
2. Run the configured formatter and linter.
3. Inspect the final diff.
4. Report what was changed and what was actually tested.
5. Disclose any tests that could not be run.

## 11. Documentation

Keep documentation synchronized with implementation.

Document:

- Architecture and module boundaries.
- Installation and development setup on EndeavourOS.
- Configuration options and defaults.
- RouterOS permissions and connection setup.
- Database schema and migration process.
- Service management and logs.
- Network ports and access restrictions.
- Troubleshooting procedures.
- Backup and recovery.
- Known limitations and future improvements.

Prefer reproducible commands and concrete examples. Do not document unimplemented features as available.

## 12. Git and change management

- Make focused changes that are easy to review.
- Do not modify unrelated files.
- Do not discard uncommitted user changes.
- Do not force-push, reset branches destructively or rewrite history without explicit approval.
- Do not commit secrets, generated databases, caches, local virtual environments or machine-specific configuration.
- Maintain an appropriate `.gitignore`.
- Update tests and documentation when behavior changes.
- Use clear commit messages when asked to commit changes.
- Preserve backwards compatibility where practical; explicitly document breaking changes.

## 13. Development priorities

Prioritize implementation in this order:

1. Reliable router connection and capability discovery.
2. Correct collection and calculation of metrics.
3. Persistent historical data.
4. Connectivity and outage tracking.
5. A usable network dashboard.
6. Operational reliability and security.
7. Alerting and additional monitoring modules.

Do not implement future modules prematurely. Keep the architecture extensible while delivering a fully functional first release.

## Definition of quality

A feature is complete only when its behavior is implemented, tested to an appropriate degree, documented and integrated into the existing architecture.

Correctness, security and maintainability take precedence over unnecessary abstraction, visual complexity and feature count.
