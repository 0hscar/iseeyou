# RouterOS read-only discovery

The RouterOS REST API over HTTPS reads system resources, interface metadata, and interface counters. RouterOS documents REST as a JSON wrapper for its API, available through the `www-ssl` service. iSeeYou uses only `GET` requests for `/rest/system/resource` and `/rest/interface`; it does not change router configuration.

This choice keeps the integration to standard HTTPS/JSON and lets the client validate the router certificate. The binary RouterOS API uses a custom sentence protocol and API-SSL service; SNMPv3 is standardized and may be a better choice for broad interface-counter collection, but RouterOS-specific system data requires its MIB/OID mappings. REST supplies cumulative `rx-byte` and `tx-byte` interface counters, so iSeeYou calculates rates from successive reads.

## Router prerequisites

Configure these manually in RouterOS; iSeeYou does not enable services, add accounts, alter firewall rules, or install certificates:

- Enable `www-ssl` and configure a certificate trusted by the workstation. Do not enable the unencrypted `www` service for monitoring.
- The certificate must identify the exact address used in `host`: for `192.168.88.1`, it needs an IP subject alternative name (`IP:192.168.88.1`). A matching common name alone is not sufficient for IP verification. Alternatively, connect with a DNS name present in the certificate's DNS subject alternative names.
- Restrict HTTPS management access to the iSeeYou workstation or another trusted management network.
- Create a dedicated user group with exactly the `read`, `api`, and `rest-api` policies, then assign a dedicated monitoring user to it. RouterOS REST authenticates through the API, so all three are required even though iSeeYou only sends read-only GET requests. Do not grant `write`, `policy`, or other unrelated permissions, and do not use the router administrator account.
- Export the issuing CA certificate as PEM if it is not already trusted by the workstation. Configure its local path as `ca_file`; certificate and hostname verification remain enabled.

RouterOS documentation describes `www-ssl` as the HTTPS service for REST, HTTP Basic authentication, JSON string values, and the required `read`, `api`, and `rest-api` group policies:

- [RouterOS REST API](https://manual.mikrotik.com/docs/developer-guides/rest-api/)
- [RouterOS users and group policies](https://help.mikrotik.com/docs/spaces/ROS/pages/8978504/Users)
- [RouterOS API and API-SSL](https://help.mikrotik.com/docs/spaces/ROS/pages/47579160/API)

## iSeeYou configuration

Copy `config.example.toml` to the ignored local file `config.toml`, then uncomment and set the `[router]` values:

```toml
[router]
host = "router.lan"
port = 443
username = "isee-monitor"
ca_file = "/home/your-user/.config/isee/router-ca.pem"
timeout_seconds = 5
```

If the router certificate chains to a CA trusted by the operating system, omit `ca_file`. The HTTPS client verifies the certificate chain and address, and does not use environment-configured HTTP proxies for router requests.

Provide the password through the process environment variable `ISEE_ROUTER_PASSWORD`, not in TOML or source control. In Fish, run these commands in the same terminal. Type the actual router password at the hidden prompt and press Enter:

```fish
read -s -P "Router password: " ISEE_ROUTER_PASSWORD
set -gx ISEE_ROUTER_PASSWORD $ISEE_ROUTER_PASSWORD
.venv/bin/isee router discover
set -e ISEE_ROUTER_PASSWORD
```

The final command removes the password from the current shell. Run it even if discovery fails; closing the shell or restarting the workstation also clears the variable. The password is not persisted by iSeeYou.

For scheduled collection, keep the variable exported while the API is running. Start `.venv/bin/isee` in that terminal, stop it with Ctrl-C when finished, then run `set -e ISEE_ROUTER_PASSWORD`. The API refuses to start collection when a configured router has no password in the environment.

The command prints uptime, CPU load, memory totals, and discovered interface identifiers, names, types, link state, and available counters as JSON. A connection timeout, certificate error, rejected credential, denied permission, or malformed RouterOS response causes a nonzero failure instead of returning success-shaped empty data.

## Scheduled collection

When `[router]` is configured, starting the iSeeYou API starts the collector. It polls at `collection.interval_seconds` (10 seconds by default), stores raw interface counters and derived bit-per-second rates in SQLite, and persists router resource values and configured connectivity results. The default database is `data/isee.sqlite3`; its parent directory is created as needed. Configure `collection.database_path` for another location.

An empty `collection.interfaces` list collects all interfaces. If set, it selects interface names exactly as RouterOS reports them. Avoid summing a bridge and its member ports together: their counters can represent the same traffic. The router's `.id` is saved to detect interface replacement between samples. The first sample, missing counters, a reset, a reboot, an interface replacement, a non-positive time interval, or a long sample gap is recorded with no throughput rate; missing or invalid data is not stored as zero.

RouterOS documents `/interface print stats` properties such as `rx-byte`, `tx-byte`, `rx-packet`, `tx-packet`, `rx-error`, and `tx-error`. Its interface documentation also warns that hardware-offloaded traffic may be absent from these software interface counters. Fast Path counters are separate; iSeeYou currently stores the documented general counters and does not claim to measure hardware-offloaded traffic. See [Interface stats and monitor-traffic](https://help.mikrotik.com/docs/spaces/ROS/pages/139526175/Interface%20stats%20and%20monitor-traffic) and the [interface CLI reference](https://manual.mikrotik.com/docs/cli-reference/interface/).

Rates are stored in bits per second: router RX is traffic received by the router (typically download on a WAN interface), and router TX is traffic sent by the router (typically upload on a WAN interface). These are per-interface values, not an inferred whole-network total.

Connectivity targets are optional `[[collection.targets]]` entries with a unique name, host, and TCP port. Each collection cycle attempts the connection sequentially up to `probes_per_target` times per target (targets run concurrently) with the configured timeout; persisted latency is the average successful TCP connection time, and failed attempts are recorded as a probe-failure percentage. This includes DNS resolution time for hostnames and records DNS resolution failures separately; it is not ICMP ping or true packet-loss measurement. The router's own REST polls indicate router reachability separately. A TCP failure means only that the configured service could not be reached, not that the whole internet is down.

Check collector state and freshness at `/health/collector`. The ordinary `/health` endpoint reports application health separately. The SQLite database and new parent directory are created with owner-only permissions; stop iSeeYou before copying the database for a consistent backup.

Example collection configuration:

```toml
[collection]
interval_seconds = 10
database_path = "data/isee.sqlite3"
interfaces = ["ether1"]
probes_per_target = 3
probe_timeout_seconds = 2

[[collection.targets]]
name = "public-https"
host = "1.1.1.1"
port = 443
```
