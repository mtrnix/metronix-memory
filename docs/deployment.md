# Deployment Checklist

This guide covers the minimum security and networking steps required to deploy Metronix Memory beyond localhost.

## 1. Change All Default Secrets

Before exposing Metronix Memory to a network, you **must** replace all default secrets and API keys in your `.env` file.

### Critical Variables to Change

- **`METATRON_MCP_API_KEY`** — Bearer token for the MCP endpoint (used by Hermes, Cursor, Claude Desktop)
  - Generate: `openssl rand -hex 32`
  - Replace the placeholder value with your generated token

- **`METATRON_SECRET_KEY`** — JWT signing key (required if you enable `AUTH_ENABLED=true`)
  - Default: `develop-secret-key-change-in-prod`
  - For production: use `openssl rand -hex 32`

- **`FERNET_KEY`** — Encryption key for stored connector credentials
  - Default: placeholder value in `.env.example`
  - Generate if not present: `python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"`

- **`METATRON_OPENAI_COMPAT_KEY`** — Optional static API key for OpenAI-compatible clients (Open WebUI, third-party tools)
  - Leave empty to use per-user keys, or set to a strong value: `openssl rand -hex 32`

- **`DEEPSEEK_API_KEY`** / **`OPENROUTER_API_KEY`** / **`CUSTOM_LLM_API_KEY`** — If using external LLM providers
  - Obtain from the respective provider and keep secret

### Never Commit `.env` to Version Control

Add `.env` to `.gitignore` if not already present:
```bash
echo ".env" >> .gitignore
```

## 2. Restrict Exposed Ports

By default, all services bind to `0.0.0.0` (all network interfaces) for development convenience. For production, restrict access to only necessary ports.

### Internet-Facing Ports

Only these ports should be exposed to the internet:

- **8001** — API server (primary entry point)
- **3080** — Open WebUI (optional; only if using the web UI)

### Internal Services (Close These to the Internet)

Firewall off the following ports or bind them to `127.0.0.1`:

| Service | Port | Action |
|---------|------|--------|
| PostgreSQL | 5433 | Block from internet; internal only |
| Qdrant HTTP | 6335 | Block from internet; internal only |
| Qdrant gRPC | 6336 | Block from internet; internal only |
| Neo4j HTTP | 7475 | Block from internet; internal only |
| Neo4j Bolt | 7688 | Block from internet; internal only |
| Redis | 6380 | Block from internet; internal only |
| Ollama | 11435 | Block from internet; internal only |
| SPLADE | 8080 | Block from internet; internal only |
| Embedding Proxy | 8002 | Block from internet; internal only |

### How to Restrict Ports in Docker Compose

In `docker-compose.full.yml`, modify the `ports:` directives for internal services:

**Before (exposes to all interfaces):**
```yaml
postgres:
  ports:
    - "5433:5432"
```

**After (internal-only access):**
```yaml
postgres:
  ports:
    - "127.0.0.1:5433:5432"
```

Or remove the `ports:` section entirely if you only access from within the Docker network.

For the API service, keep it open if it needs internet access:
```yaml
api:
  ports:
    - "8001:8000"
```

Then use a reverse proxy (see section 3) to handle HTTPS termination and routing.

## 3. HTTPS Setup

Metronix Memory does not terminate TLS itself. Use a reverse proxy to handle HTTPS and forward requests to the API.

### Recommended Reverse Proxies

#### Option A: Caddy (Simplest)

Caddy automatically provisions and renews TLS certificates via Let's Encrypt.

1. Install Caddy on your host or in a Docker container
2. Create a `Caddyfile`:
   ```
   your-domain.com {
     reverse_proxy 127.0.0.1:8001
   }
   ```
3. Run Caddy:
   ```bash
   caddy run --config Caddyfile
   ```
4. Caddy will automatically obtain and renew an HTTPS certificate

#### Option B: Nginx

1. Install nginx
2. Create `/etc/nginx/sites-available/metatron.conf`:
   ```nginx
   upstream metatron {
     server 127.0.0.1:8001;
   }
   
   server {
     listen 80;
     server_name your-domain.com;
     return 301 https://$server_name$request_uri;
   }
   
   server {
     listen 443 ssl;
     server_name your-domain.com;
     
     ssl_certificate /etc/letsencrypt/live/your-domain.com/fullchain.pem;
     ssl_certificate_key /etc/letsencrypt/live/your-domain.com/privkey.pem;
     
     location / {
       proxy_pass http://metatron;
       proxy_set_header Host $host;
       proxy_set_header X-Real-IP $remote_addr;
       proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
       proxy_set_header X-Forwarded-Proto $scheme;
     }
   }
   ```
3. Use [Certbot](https://certbot.eff.org/) to provision TLS certificates:
   ```bash
   certbot certonly --standalone -d your-domain.com
   ```
4. Enable the site and reload:
   ```bash
   sudo ln -s /etc/nginx/sites-available/metatron.conf /etc/nginx/sites-enabled/
   sudo systemctl reload nginx
   ```

#### Option C: Traefik (Container-Native)

1. Add a Traefik service to your Docker Compose stack
2. Label the API service for automatic HTTPS routing:
   ```yaml
   api:
     labels:
       - "traefik.enable=true"
       - "traefik.http.routers.metatron.rule=Host(\`your-domain.com\`)"
       - "traefik.http.routers.metatron.entrypoints=websecure"
       - "traefik.http.routers.metatron.tls.certresolver=letsencrypt"
   ```
3. Configure Traefik to use Let's Encrypt for automatic certificate provisioning

### Update Configuration After HTTPS Setup

Once HTTPS is active, update any references to the Metatron URL in agent configurations and environment variables:

- **In MCP/agent configs**: Update the connection URL from `http://localhost:8001` to `https://your-domain.com`
- **In `.env`**: Update `METATRON_OPENWEBUI_METATRON_URL` if using Open WebUI integration
- **In CORS settings**: If `CORS_ORIGINS=*`, consider restricting to specific origins after HTTPS is enabled

## Next Steps

This checklist covers the bare minimum for a secure network-facing deployment. For additional production considerations (monitoring, logging, backups, scaling, secrets management), refer to the full production operations runbook (planned; see GitHub issues).

For questions or to contribute deployment best practices, open an issue on the [Metronix Memory repository](https://github.com/mtrnix/metronix-memory).
