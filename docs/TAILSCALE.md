# Access dashboards from your phone via Tailscale

`localhost` only works on the Mac mini. With Tailscale, your phone can reach the dashboards over your private tailnet (works at home or away).

## 1. Install Tailscale (once)

On **Mac mini** and **phone**:

- Mac: https://tailscale.com/download/mac (or `brew install --cask tailscale`)
- iPhone: App Store → **Tailscale**

Sign both devices into the **same** Tailscale account.

## 2. Find your Mac mini Tailscale address

On the Mac mini:

```bash
tailscale ip -4
```

Example: `100.64.12.34`

If **MagicDNS** is enabled in [Tailscale admin](https://login.tailscale.com/admin/dns), you can also use the machine name:

```bash
tailscale status | head -5
```

Example: `steves-mac-mini.your-tailnet.ts.net`

## 3. Start dashboard servers (bind all interfaces)

The serve scripts use `--bind 0.0.0.0` so Tailscale can connect.

```bash
cd ~/agents/trading-agent
source venv/bin/activate

# Options (PLUG / options agent)
./serve_options_dashboard.sh

# Equity (stocks) — second Terminal window
./serve_dashboard.sh
```

Or double-click the Desktop shortcuts (after `git pull` for latest scripts).

## 4. Open on your phone

Turn **Tailscale ON** on the phone, then open Safari:

| Dashboard | URL |
|-----------|-----|
| **Options** | `http://100.x.x.x:8081/options_dashboard.html` |
| **Equity** | `http://100.x.x.x:8080/dashboard.html` |

Replace `100.x.x.x` with your Mac mini’s Tailscale IP.

**Add to Home Screen** (Share → Add to Home Screen) for one-tap access.

## 5. If the phone cannot connect

### macOS Firewall

**System Settings → Network → Firewall**

- Turn firewall **Off** temporarily to test, or
- **Options** → allow **Python** / **Terminal** incoming connections

### Tailscale ACLs

Default tailnets allow all device-to-device traffic. If you use custom ACLs, allow TCP ports **8080** and **8081** to the Mac mini.

### Server not running

The URL only works while `serve_*_dashboard.sh` is running on the Mac mini.

### Stale data

Rebuild before serving:

```bash
python3 options_dashboard.py   # options
python3 dashboard.py           # equity
```

## Quick setup script

```bash
cd ~/agents/trading-agent
chmod +x shortcuts/setup_tailscale_dashboards.sh
./shortcuts/setup_tailscale_dashboards.sh
```

Prints your Tailscale URLs and firewall tips.

## Optional: Tailscale Serve (HTTPS)

Expose a service with HTTPS inside your tailnet only:

```bash
tailscale serve --bg --https=8443 http://127.0.0.1:8081
```

Then use the HTTPS URL Tailscale prints (`tailscale serve status`).

This does **not** expose dashboards to the public internet unless you explicitly use `tailscale funnel`.
