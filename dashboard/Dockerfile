# syntax=docker/dockerfile:1

# ---- Build stage: compile the Vite app into static files ----
FROM node:20-alpine AS build
WORKDIR /app

# Install dependencies from the lockfile only (reproducible, cached layer).
COPY package.json package-lock.json ./
RUN npm ci

# Build. No build args or env vars are read: no secrets and no API token
# are embedded. The app calls the Brain through relative /api paths.
COPY index.html tsconfig.json vite.config.ts vitest.config.ts ./
COPY src ./src
RUN npm run build

# ---- Final stage: static output only (no Node, no sources, no node_modules) ----
# Served by Caddy; the compose file shares /srv with the caddy service.
FROM busybox:1.36
COPY --from=build /app/dist /site
# /srv is the shared volume. On every start, replace its contents with this
# image's build, so `docker compose up -d --build` publishes a new dashboard.
RUN mkdir -p /srv && chown 65534:65534 /srv
USER 65534:65534
CMD ["sh", "-c", "rm -rf /srv/* && cp -r /site/. /srv/ && exec sleep infinity"]
