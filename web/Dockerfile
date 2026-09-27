# syntax=docker/dockerfile:1.7
# build context: repo root (docker-compose.yml sets `dockerfile: web/Dockerfile`,
# `context: .`) — needed to see pnpm-workspace.yaml and the root lockfile.

FROM node:24-alpine AS base
ENV PNPM_HOME=/pnpm PATH="/pnpm:$PATH"
RUN corepack enable
WORKDIR /app

FROM base AS deps
# package.json pins `packageManager` — without it here, corepack has nothing to read in /app
# and resolves pnpm to whatever's latest instead of the pinned version. Its `prepare` script
# (`lefthook install`, git-hook setup for local dev) is stripped: it hard-fails without a real
# .git directory, which the build context doesn't have.
COPY package.json pnpm-workspace.yaml pnpm-lock.yaml* ./
RUN node -e "const p=require('./package.json'); delete p.scripts; require('fs').writeFileSync('package.json', JSON.stringify(p))"
COPY web/package.json web/package.json
RUN --mount=type=cache,id=pnpm,target=/pnpm/store \
    pnpm install --frozen-lockfile

# the one stage that isn't alpine: `pnpm test` runs vitest's `client` (browser-mode) project
# and the Playwright e2e suite, and Playwright ships no musl chromium build — on alpine the
# browser is simply not installable. Baked into the image rather than left to `test:e2e`'s own
# `playwright install`, which otherwise re-downloads chromium on every `docker compose run --rm`.
FROM node:24-bookworm-slim AS dev
ENV PNPM_HOME=/pnpm PATH="/pnpm:$PATH"
RUN corepack enable
WORKDIR /app
COPY package.json pnpm-workspace.yaml pnpm-lock.yaml* ./
RUN node -e "const p=require('./package.json'); delete p.scripts; require('fs').writeFileSync('package.json', JSON.stringify(p))"
COPY web/package.json web/package.json
RUN --mount=type=cache,id=pnpm,target=/pnpm/store pnpm install --frozen-lockfile
RUN cd web && pnpm exec playwright install --with-deps chromium
COPY web/ web/
WORKDIR /app/web
EXPOSE 5173
CMD ["pnpm", "dev", "--host", "0.0.0.0", "--port", "5173"]

FROM base AS build
# same packageManager pin `deps` needed — corepack re-resolves it per stage, and this stage
# doesn't inherit `deps`' filesystem, only its node_modules.
COPY --from=deps /app/package.json /app/pnpm-workspace.yaml ./
COPY --from=deps /app/node_modules ./node_modules
COPY --from=deps /app/web/node_modules ./web/node_modules
COPY web/ web/
WORKDIR /app/web
RUN pnpm build && pnpm prune --prod

FROM node:24-alpine AS prod
WORKDIR /app
ENV NODE_ENV=production
COPY --from=build /app/web/build ./build
COPY --from=build /app/web/node_modules ./node_modules
COPY --from=build /app/web/package.json ./
USER node
EXPOSE 3000
CMD ["node", "build"]
