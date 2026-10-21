# Project: iSeeYou — Self-Hosted Infrastructure Observability

## 1. Project vision

Build **iSeeYou**, a modular, self-hosted infrastructure monitoring and observability platform. The goal is to provide a unified view of the health, performance, availability and behavior of my infrastructure through a central dashboard.

The platform must be designed for gradual expansion. Each functional module follows the naming convention `isee[module]`, such as:

- `iseeNetwork` — network monitoring (first module)
- `iseeSystem` — system resource and hardware monitoring
- `iseeServices` — service and application availability
- `iseeLogs` — centralized log collection and analysis
- `iseeAlerts` — alert rules and notification delivery
- `iseeSecurity` — security events and suspicious activity

These are logical module names, not necessarily separate processes or repositories. Begin with a single deployable application and keep module boundaries clear enough to allow future separation if justified.

## 2. Initial environment

Develop and test against my existing setup:

- **Workstation:** EndeavourOS (Arch Linux), running Hyprland on Wayland.
- **Shell:** Fish.
- **Router:** MikroTik hAP ax3 running RouterOS 7.22.
- **Network management:** NetworkManager.
- **LAN:** Wired Ethernet, interface `eno1`, with a home LAN and existing MikroTik-managed network services.
- **Remote infrastructure:** An Ubuntu VPS (or multiple) used for self-hosted services and game-server administration.
- **Development environment:** Zed, Git and the Linux terminal.

Do not assume a Raspberry Pi, dedicated monitoring server or additional hardware is available. The initial version must run on my existing workstation.

The workstation is not always powered on. Account for this limitation in the architecture and document how to migrate the collector and storage to an always-on Linux host later.

## 3. Core requirements

### Self-hosted and free

- Use open-source software without mandatory subscriptions, proprietary hosted services or external telemetry.
- Do not require a cloud account.
- Store monitoring data locally.
- Do not make outbound connections except when explicitly required by a configured monitoring target, update check or notification integration.
- Avoid unnecessary infrastructure and dependencies.
- Support running as an unprivileged Linux user wherever possible.

### Modular architecture

- Keep each `isee[module]` responsible for a clearly defined domain.
- Define explicit interfaces for collectors, data storage, health checks, alert rules and dashboard data.
- Separate collection, processing, storage, API and presentation.
- Make it possible to add modules without rewriting the existing application.
- Avoid premature microservices, Kubernetes and distributed infrastructure.
- Use shared authentication, configuration, storage conventions and UI components where appropriate.

### Reliability and maintainability

- Provide configuration validation and useful error messages.
- Handle unavailable devices, timeouts and intermittent connectivity gracefully.
- Include structured logs, health endpoints and sensible shutdown behavior.
- Include automated tests for critical functionality.
- Document installation, configuration, upgrades, backups and troubleshooting.
- Pin or constrain dependencies appropriately.
- Never silently discard collection errors or present missing data as zero.

## 4. First module: `iseeNetwork`

Build the first working module around the MikroTik hAP ax3.

### Data collection

Collect the following where supported by RouterOS and the selected interface:

1. Router availability and uptime.
2. CPU utilization and memory usage.
3. WAN interface upload and download throughput.
4. LAN and selected interface traffic.
5. Interface link state, errors and packet counters.
6. Latency and packet loss to configurable targets.
7. Device availability for configurable LAN hosts.
8. Historical measurements and network outage events.

Prefer the RouterOS API over SNMP when it provides the required information cleanly. Evaluate SNMPv3 as an alternative, particularly for standardized interface metrics. Explain the trade-offs before committing to a collection method.

Do not assume that all RouterOS metrics are available through every protocol or firmware version. Verify the implementation against RouterOS 7.22 and handle unsupported metrics explicitly.

### Bandwidth calculations

- Calculate upload and download rates from cumulative interface byte counters.
- Account for counter resets, device reboots, interface changes and counter wraparound.
- Never interpret the first counter reading as a valid throughput measurement.
- Store raw counter readings or enough metadata to diagnose calculation problems.
- Clearly distinguish bits per second from bytes per second.
- Identify interfaces by stable identifiers where possible, not solely by display names.
- Document whether hardware-offloaded traffic or FastTrack affects the availability or interpretation of any measurements.

### Connectivity monitoring

Implement configurable probes for:

- The MikroTik gateway.
- At least one public IP address.
- An optional DNS resolver or hostname.
- Selected LAN devices.

Measure latency and packet loss independently for each target.

Avoid interpreting a failed ICMP probe alone as proof that the internet is down. Support multiple checks and make the dashboard distinguish local gateway failure, upstream reachability failure and DNS failure.

Use configurable timeouts, intervals and failure thresholds. Avoid generating repeated alerts for a single prolonged outage.

### Dashboard

Create a clean, responsive dashboard with the following views:

**Overview**

- Current network status.
- Router availability.
- Current WAN upload/download throughput.
- Current latency and packet loss.
- Active alerts and recent outages.
- Data freshness and collector health.

**Network interfaces**

- Interface status and identifying information.
- Upload/download graphs.
- Interface errors and packet statistics.
- Configurable time ranges.

**Connectivity**

- Reachability and latency by target.
- Packet-loss history.
- Outage start and end times.
- Diagnostic information to help isolate failures.

**History**

- Traffic and latency trends.
- Historical device availability.
- Searchable outage events.
- Clear indicators for gaps in collected data.

Do not overload the initial interface with metrics that cannot be reliably collected.

## 5. Suggested technology stack

Evaluate these options and select the simplest architecture that meets the requirements.

- **Backend:** Python with FastAPI.
- **Collection:** Python background workers with asynchronous I/O where useful.
- **Router integration:** RouterOS API client or a suitable SNMP library.
- **Initial database:** SQLite with migrations.
- **Frontend:** A lightweight web interface with interactive time-series graphs, Typescript + React (if it's the wisest choice).
- **Visualization:** Plotly or another suitable open-source charting library.
- **Configuration:** Validated TOML or YAML configuration.
- **Process management:** systemd user service during development, with a documented option for a system service on an always-on host.
- **Testing:** pytest and appropriate integration-test fixtures.
- **Packaging:** A reproducible Python environment and clear installation instructions.

Do not add Prometheus, Grafana, Redis, PostgreSQL or a message broker by default. Introduce another component only when there is a concrete technical reason. Explain any proposed departure from this stack.

## 6. Security requirements

The router and monitoring service must not be exposed directly to the public internet.

- Use dedicated, least-privilege RouterOS credentials.
- Restrict management access to the monitoring host or trusted management network.
- Prefer encrypted authentication where supported.
- Do not use the RouterOS administrator account for routine monitoring.
- Never store passwords or API tokens in source code or commit them to Git.
- Keep secrets out of logs, error messages and the frontend.
- Bind the development server to localhost by default.
- If remote dashboard access is added, require authentication and a deliberate network-access configuration.
- Validate all user-supplied configuration and API parameters.
- Do not introduce privileged packet capture or firewall modifications unless explicitly required.
- Do not change router settings automatically during installation.

Document the minimum RouterOS configuration needed to enable monitoring and how to reverse it.

## 7. Data retention and performance

- Make polling intervals configurable.
- Start with a reasonable interval, such as 10 seconds for interface and connectivity metrics.
- Keep database writes efficient.
- Implement a configurable retention policy.
- Preserve enough resolution for short outages while controlling database growth.
- Consider aggregation of older measurements if the implementation needs it.
- Display the timestamp of the latest successful collection.
- Avoid aggressive polling that could burden the router or collector.

## 8. Future modules

Design the initial application so future modules can be introduced incrementally.

### `iseeSystem`

Monitor Linux CPU, RAM, storage, temperatures, network interfaces and system load.

### `iseeServices`

Monitor HTTP endpoints, TCP ports, DNS resolution, certificates and service health.

### `iseeLogs`

Collect and search logs from selected Linux hosts and services.

### `iseeAlerts`

Provide reusable alert rules, deduplication, cooldowns, recovery notifications and optional email or Telegram integrations.

### `iseeSecurity`

Add security-related telemetry, authentication events and suspicious network behavior, subject to available data and explicit configuration.

Future modules must reuse common infrastructure rather than implementing their own independent databases, authentication mechanisms and dashboard frameworks without justification.

## 9. Development workflow

Work incrementally rather than generating the entire platform at once.

**Phase 1 — Foundation**

- Define the architecture and module boundaries.
- Create the repository structure.
- Set up dependency management, configuration validation, logging and tests.
- Implement a minimal application health endpoint.

**Phase 2 — Router integration**

- Establish a read-only connection to the MikroTik.
- Discover interfaces and retrieve supported system metrics.
- Validate permissions and handle connection failures.

**Phase 3 — Collection and storage (implementation complete)**
- [x] Implement scheduled polling.
- [x] Calculate interface throughput and configurable TCP connectivity metrics.
- [x] Store timestamped raw counters and measurements in SQLite.
- [x] Test reboot, timeout, counter-reset and missing-data scenarios.

The live `ether1` counters and calculated rates have been verified against the configured MikroTik. TCP connectivity targets remain opt-in and must be configured before those metrics are collected. The collector reports TCP probe failures, not ICMP packet loss. Phase 4 derives unreachable windows from the stored TCP samples; durable outage-event transitions are not persisted.

**Phase 4 — Dashboard (implementation complete)**

- [x] Implement Overview, Interfaces and Connectivity views with modular navigation.
- [x] Add locally hosted interactive history graphs, bounded time-range selection and derived unreachable-period history.
- [x] Distinguish unavailable, stale, invalid and missing data from healthy readings.

The dashboard is served by FastAPI/Jinja2 with plain CSS and JavaScript and locally vendored uPlot assets. It introduces no separate frontend service or external CDN dependency. The interface inventory shows all RouterOS interfaces and their comments; `collection.interfaces` independently controls which interfaces receive stored counter/rate history. Derived unreachable periods indicate consecutive fully failed TCP probe cycles only; they are not ICMP packet loss or persisted outage events. The dashboard has no authentication and must remain on localhost or an appropriately secured trusted network.

**Phase 5 — Operational readiness**

- Add retention, configuration documentation, automated tests and service management.
- Test startup, shutdown, restart and recovery from router unavailability.
- Document backup and restore procedures.

**Phase 6 — Expansion**

- Evaluate the next module based on actual needs.
- Preserve backwards compatibility for configuration and stored data where practical.
- Avoid implementing future modules before the initial network monitoring workflow is reliable.

At each phase, provide working code, tests and documentation before moving on. Do not merely produce a plan or pseudocode.

## 10. Expected deliverables

- A working Git repository.
- A clear project directory structure.
- A documented architecture and module interface.
- An example configuration with no real credentials.
- A functional `iseeNetwork` implementation.
- A usable web dashboard.
- Database schema and migration strategy.
- Automated unit and integration tests.
- Installation and startup instructions for EndeavourOS.
- systemd service configuration.
- A RouterOS setup guide with least-privilege permissions.
- Troubleshooting and security documentation.
- A roadmap for migrating to an always-on Linux host and adding future modules.

## 11. Instructions to the coding agent

Before implementing, inspect the repository and identify existing conventions. If the repository is empty, propose a concise directory structure and architecture.

Explain key architectural decisions, trade-offs and assumptions. Verify library APIs and RouterOS integration details instead of inventing them.

Prefer small, testable changes over large, unreviewable code dumps. Do not overwrite existing configuration or perform destructive operations without approval.

Begin by presenting the proposed architecture, repository structure, collection protocol choice and implementation plan. Then implement Phase 1 and continue incrementally.

**Definition of done for the first release:** I can run iSeeYou on EndeavourOS, connect it securely to my MikroTik hAP ax3, see current and historical WAN traffic, monitor router availability and latency, identify outages, and restart the service without losing previously collected data.
