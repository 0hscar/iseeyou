# RouterOS read-only discovery

Phase 2 uses the RouterOS REST API over HTTPS to read system resources and discover interfaces. RouterOS documents REST as a JSON wrapper for its API, available through the `www-ssl` service. iSeeYou uses only `GET` requests for `/rest/system/resource` and `/rest/interface`; it does not change router configuration.

This choice keeps the initial integration to standard HTTPS/JSON and lets the client validate the router certificate. The binary RouterOS API uses a custom sentence protocol and API-SSL service; SNMPv3 is standardized and may be a better choice for broad interface-counter collection, but RouterOS-specific system data requires its MIB/OID mappings. Revisit the transport if later metrics or polling performance warrant it.

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

The command prints uptime, CPU load, memory totals, and discovered interface identifiers, names, types, and link state as JSON. A connection timeout, certificate error, rejected credential, denied permission, or malformed RouterOS response causes a nonzero failure instead of returning success-shaped empty data.

## Current read scope

The client requests RouterOS system resource properties and interface metadata. It does not yet poll counters, calculate throughput, store measurements, or run as a background collector; those belong to the collection and persistence phases.
