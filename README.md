# iSeeYou

iSeeYou is a self-hosted infrastructure monitoring and observability platform. The current implementation provides validated settings, structured application logs, read-only RouterOS discovery, scheduled network collection with SQLite persistence, and a lightweight web dashboard.

## Development setup

Requires Python 3.11 or later.

```sh
python -m venv .venv
.venv/bin/python -m pip install --upgrade pip
.venv/bin/python -m pip install -e '.[dev]'
cp config.example.toml config.toml
```

Start the API on the configured host and port:

```sh
.venv/bin/isee
```

The default bind address is `127.0.0.1`. Open `http://127.0.0.1:8000/` for the dashboard. It includes Overview, Interfaces, and Connectivity views; chart assets and scripts are served locally, with no frontend build process or external CDN requests. The dashboard distinguishes missing and stale data from healthy readings. Check the application health endpoint with:

```sh
curl http://127.0.0.1:8000/health
```

Run the test suite with:

```sh
.venv/bin/python -m pytest
```

## RouterOS discovery

The MikroTik REST API is used over HTTPS. Configure the `[router]` section in `config.toml`, provide the account password through `ISEE_ROUTER_PASSWORD`, and run `.venv/bin/isee router discover`. See [docs/ROUTEROS.md](docs/ROUTEROS.md) for the Fish password prompt, certificate, least-privilege account, and service requirements.

When the API starts with a `[router]` section, it runs the network collector at the configured interval and writes timestamped samples to the configured SQLite database. Check `/health/collector` for collector state and freshness. Set selected interfaces and explicit TCP connectivity targets under `[collection]`; no connectivity target is probed unless configured.

The Interfaces inventory lists every interface reported by RouterOS, including its comment (for example, `WAN`). `collection.interfaces` controls which interfaces get counter/rate history; other interfaces remain visible and are marked not monitored.

The initial connectivity implementation measures TCP connection success, connection latency, and failed-probe percentage for each configured host and port. It is not an ICMP ping and does not by itself prove internet availability.

The dashboard exposes `/`, `/interfaces`, and `/connectivity`. It provides bounded history queries over the latest 1, 6, 24, or 168 hours and derives unreachable periods from consecutive samples where every TCP probe to a target failed. These are derived windows, not persisted outage events; they are not ICMP packet-loss measurements or proof of an internet outage. History is downsampled to at most approximately 1,000 points per chart.

Phase 3 collection and SQLite persistence are implemented, and live `ether1` counter-derived rates have been verified. Connectivity probes are opt-in. True packet-loss measurement, durable outage-event records, authentication, and remote-access configuration are not implemented. Keep the dashboard on localhost or behind a separately secured trusted network; do not expose the default unauthenticated dashboard directly to the public internet.

## Configuration

The application reads TOML from `config.toml` in the current directory by default. Set `ISEE_CONFIG` to use a different file. Configuration is validated at startup; unknown keys, invalid ports, and invalid log levels produce an error rather than being silently ignored.

The example configures the local HTTP server and log level, with an optional RouterOS section. Keep real configuration and credentials out of Git; the router password is supplied through the environment.
