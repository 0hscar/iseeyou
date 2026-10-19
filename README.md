# iSeeYou

iSeeYou is a self-hosted infrastructure monitoring and observability platform. The current implementation provides validated settings, structured application logs, an HTTP health endpoint, and one-shot read-only RouterOS system and interface discovery.

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

The default bind address is `127.0.0.1`. Check the application health endpoint with:

```sh
curl http://127.0.0.1:8000/health
```

Run the test suite with:

```sh
.venv/bin/python -m pytest
```

## RouterOS discovery

Phase 2 uses the MikroTik REST API over HTTPS. Configure the `[router]` section in `config.toml`, provide the account password through `ISEE_ROUTER_PASSWORD`, and run `.venv/bin/isee router discover`. See [docs/ROUTEROS.md](docs/ROUTEROS.md) for the Fish password prompt, certificate, least-privilege account, and service requirements.

## Configuration

The application reads TOML from `config.toml` in the current directory by default. Set `ISEE_CONFIG` to use a different file. Configuration is validated at startup; unknown keys, invalid ports, and invalid log levels produce an error rather than being silently ignored.

The example configures the local HTTP server and log level, with an optional RouterOS section. Keep real configuration and credentials out of Git; the router password is supplied through the environment.
