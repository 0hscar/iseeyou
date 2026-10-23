# Local systemd deployment

This setup runs iSeeYou and Caddy as unprivileged systemd user services. The
application remains bound to `127.0.0.1:8000`; Caddy provides HTTPS and
password authentication on port `8443`, and limits access to the IPv4 CIDR
ranges set in the private Caddy environment file. Configure the host firewall
separately to permit only those same networks.
Replace every `<...>` value below with values for your own network; keep real
addresses and subnets out of this repository.

The example units expect the checkout at `~/code/iseeyou`. If it is elsewhere,
edit the working directory, config path, executable path, and writable data
path in `deploy/systemd/user/isee.service` before installing it.

## Install and prepare

Install Caddy from the EndeavourOS/Arch repositories:

```sh
sudo pacman -S caddy
```

Create the private service configuration directory and make sure the SQLite
directory is writable only by your account:

```sh
install -d -m 700 ~/.config/isee ~/.config/caddy ~/.local/share/caddy
install -d -m 700 ~/code/iseeyou/data
```

Create the router secret file with mode `600`, then edit it to add the router
password; do not put the password in the repository or a unit file:

```text
ISEE_ROUTER_PASSWORD=replace-with-the-router-password
```

```sh
install -m 600 /dev/null ~/.config/isee/router.env
vi ~/.config/isee/router.env
```

If the router is not configured in `config.toml`, the service still requires
this file; it may be empty.

Install the Caddyfile template, then create `~/.config/isee/caddy.env`
with mode `600` and set:

```text
ISEE_DASHBOARD_ADDRESS=<DASHBOARD_HOSTNAME_OR_IP_ONLY>
ISEE_DASHBOARD_USER=choose-a-dashboard-username
ISEE_DASHBOARD_PASSWORD_HASH=replace-with-a-Caddy-bcrypt-hash
ISEE_TRUSTED_CIDRS='<TRUSTED_LAN_CIDR> <TRUSTED_VLAN_CIDR>'
```

```sh
install -m 600 deploy/caddy/Caddyfile ~/.config/isee/Caddyfile
install -m 600 /dev/null ~/.config/isee/caddy.env
vi ~/.config/isee/caddy.env
```

Set `ISEE_DASHBOARD_ADDRESS` to only the stable hostname or IP address that
clients will use to reach this host; do not include `https://`, a port, or a
trailing slash. The Caddyfile adds HTTPS and port `8443`. A DHCP reservation
or stable local DNS name is recommended. Set `ISEE_TRUSTED_CIDRS` to one or
more space-separated IPv4 CIDR ranges that should be allowed to connect.
Generate the hash interactively with
Caddy's `caddy hash-password` command and store the resulting bcrypt hash, not
the dashboard password. Protect both environment files:

```sh
chmod 600 ~/.config/isee/router.env ~/.config/isee/caddy.env
```

## Install and start the user services

Copy the unit files into the user systemd configuration directory:

```sh
install -d -m 700 ~/.config/systemd/user
install -m 600 deploy/systemd/user/isee.service deploy/systemd/user/caddy.service \
  ~/.config/systemd/user/
```

Enable lingering so these user services can start at boot without an
interactive login:

```sh
sudo loginctl enable-linger "$USER"
```

Then enable and start both units:

```sh
systemctl --user daemon-reload
systemctl --user enable --now isee.service caddy.service
```

Check service status and logs with:

```sh
systemctl --user status isee.service caddy.service
journalctl --user -u isee.service -u caddy.service
```

The dashboard should then be available at
`https://<ISEE_DASHBOARD_ADDRESS>:8443/`. Caddy's internal CA is private to this
host; install its public root certificate on each client that should trust the
dashboard:
`~/.local/share/caddy/pki/authorities/local/root.crt`. Transfer only
`root.crt`, never the CA private key. Browsers may need a restart after
installing the certificate. Caddy is configured not to install this certificate
automatically into local trust stores; install it only on clients you trust.

## Firewalld (optional)

If the host uses firewalld, run `firewall-cmd --get-active-zones` to find the
zone for its network interface. Replace `<FIREWALL_ZONE>` and each CIDR
placeholder with your own values in rules like these. Add one rule per trusted
network:

```sh
sudo firewall-cmd --permanent --zone="<FIREWALL_ZONE>" \
  --add-rich-rule='rule family="ipv4" source address="<TRUSTED_LAN_CIDR>" port port="8443" protocol="tcp" accept'
sudo firewall-cmd --permanent --zone="<FIREWALL_ZONE>" \
  --add-rich-rule='rule family="ipv4" source address="<TRUSTED_VLAN_CIDR>" port port="8443" protocol="tcp" accept'
sudo firewall-cmd --reload
```

These source-restricted rules do not open port `8443` to other sources.
Replace the angle-bracket placeholders before running the commands; do not
paste them literally. Caddy independently enforces the same source allowlist
and requires HTTP Basic authentication. Do not add a general `8443/tcp` port
opening or expose the application's port `8000`.

Any additional network must also have appropriate routing and firewall rules
to reach this host. No router or host firewall configuration is changed by
installing the repository files.

## Updating the app

This deployment runs the app from the Git checkout and its virtual environment;
it does not install a separate system-wide copy. The editable install points
to the checkout, so restarting the service loads changed Python code; rerunning
`pip install -e .` refreshes installed package metadata and dependencies. To
update it, preserve any local code changes, then:

```sh
cd ~/code/iseeyou
git status --short --branch
```

Do not continue with a pull if the worktree contains changes you need to keep;
commit or back them up first. Stop the service, then back up the database if it
exists before updating the checkout:

```sh
systemctl --user stop isee.service
if [ -f data/isee.sqlite3 ]; then
  cp -a data/isee.sqlite3 "data/isee.sqlite3.backup.$(date +%Y%m%d-%H%M%S)"
fi
git pull --ff-only
.venv/bin/python -m pip install -e .
```

The application applies its supported SQLite migrations on startup. Keep the
database backup until the updated service has started successfully. Start it
again and check status and health:

```sh
systemctl --user daemon-reload
systemctl --user start isee.service
systemctl --user status isee.service
curl http://127.0.0.1:8000/health
curl http://127.0.0.1:8000/health/collector
```

If you changed a systemd unit in the checkout, copy the updated unit file(s)
into `~/.config/systemd/user/` before `daemon-reload`. If you changed the
Caddyfile, copy it to `~/.config/isee/Caddyfile` and restart
`caddy.service`. Routine application code updates do not require restarting
Caddy.

## Troubleshooting

- `systemctl --user status isee.service`: check application startup and config
  errors.
- `curl http://127.0.0.1:8000/health/collector`: check collector health on the
  host.
- `systemctl --user status caddy.service`: check Caddy config, TLS, and
  listener errors.
- A browser certificate warning usually means the client's trust store does
  not yet trust Caddy's local root CA.
- If the dashboard hostname or IP changes, update `ISEE_DASHBOARD_ADDRESS`,
  then restart Caddy with `systemctl --user restart caddy.service`.
