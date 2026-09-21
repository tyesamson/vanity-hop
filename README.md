# Vanity Hop

Self-hosted branded URL shortener. Set a domain once, paste a long URL, get a short link on your domain. No click tracking.

## First run

Open the app and choose **Begin setup**. You create a password, set the public domain, then point DNS (and TLS) at the server.

## Run locally

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
DEV=1 PORT=8080 python run.py
```

Open [http://localhost:8080](http://localhost:8080). Data is stored in `./data`.

## Docker

Image: `ghcr.io/tyesamson/vanity-hop:latest`

Publishes port 3000 on the host so Nginx Proxy Manager can reach it by the machine’s IP. No shared Docker network is required. The data directory on the host can be empty; the container creates the database on first start.

```bash
docker run --restart=unless-stopped -d \
  --name vanity-hop \
  -p 3000:3000 \
  -v /etc/localtime:/etc/localtime:ro \
  -v /mnt/docker/vanity-hop/data:/app/data \
  -e TZ="Pacific/Auckland" \
  -e PUBLIC_ORIGIN=https://links.example.com \
  -e HTTPS_ONLY=true \
  -e FORWARDED_ALLOW_IPS=* \
  ghcr.io/tyesamson/vanity-hop:latest
```

Or build locally:

```bash
cp .env.example .env
# PUBLIC_ORIGIN=https://links.example.com
# HTTPS_ONLY=true
docker compose up --build -d
```

If both `PUBLIC_ORIGIN` and `ADMIN_PASSWORD` are set on first boot, onboarding is skipped.

## Nginx Proxy Manager

This app should sit behind NPM; it does not terminate TLS itself.

1. DNS for your short domain should point at the NPM host (`A` / `AAAA` / `CNAME`).
2. In NPM, add a **Proxy Host**:
   - Domain: your short host
   - Scheme: `http`
   - Forward hostname / IP: this machine’s IP (on the same Docker host, `172.17.0.1` usually works)
   - Forward port: `3000`
   - Forward Hostname: on
   - SSL: request a certificate, enable **Force SSL**
3. Set `PUBLIC_ORIGIN` to the public HTTPS origin (exactly as browsers see it) and `HTTPS_ONLY=true`.

WebSockets are not required. Leave port 3000 off any WAN / router forward; NPM already has 80 and 443. Local `python run.py` trusts `127.0.0.1` only.

Login is limited to 8 failures per 15 minutes per IP. Changing the password signs out every other session.

## Settings

- **Domain** — any host; copied onto short links
- **Slug prefix** — optional, off by default. Example prefix `suite_` → `https://links.example.com/suite_a3kx`
- **Branding** — name, logo, favicon, colours, background image
- **Links** — select and bulk delete, or delete everything older than a period

New slugs are a random 4-character string, with the prefix prepended when enabled.

## Environment

| Variable | Purpose |
| --- | --- |
| `PUBLIC_ORIGIN` | Public origin, e.g. `https://links.example.com` |
| `ADMIN_PASSWORD` | Optional initial password |
| `SESSION_SECRET` | Cookie signing key; generated into `data/.session_secret` if omitted |
| `HTTPS_ONLY` | `true` when served over HTTPS (also implied if `PUBLIC_ORIGIN` is `https://…`) |
| `FORWARDED_ALLOW_IPS` | IPs allowed to set `X-Forwarded-*` (default `127.0.0.1`; Compose uses `*`) |
| `DATA_DIR` | SQLite and uploads (default `./data`) |
| `PORT` | Listen port (default `3000`) |

## License

MIT. See [LICENSE](LICENSE).
