FROM node:20-alpine AS build
WORKDIR /app
COPY package.json package-lock.json ./
RUN npm ci
COPY . .
RUN npm run build

# ---------------------------------------------------------------------------
# Caddy runtime — serves the built SPA over HTTPS (internal CA by default)
# and reverse-proxies /api /health /ready /metrics to metronix-core:8000.
# Replaces the previous nginx image.
# ---------------------------------------------------------------------------
FROM caddy:2-alpine
COPY --from=build /app/dist /srv
COPY Caddyfile /etc/caddy/Caddyfile
EXPOSE 3000
CMD ["caddy", "run", "--config", "/etc/caddy/Caddyfile", "--adapter", "caddyfile"]