# syntax=docker/dockerfile:1.7
# build context: repo root (docker-compose.yml sets `dockerfile: web/Dockerfile`,
# `context: .`) — needed to see pnpm-workspace.yaml and the root lockfile.

FROM node:24-alpine AS base
ENV PNPM_HOME=/pnpm PATH="/pnpm:$PATH"
RUN corepack enable
WORKDIR /app

FROM base AS deps
COPY pnpm-workspace.yaml pnpm-lock.yaml* ./
COPY web/package.json web/package.json
RUN --mount=type=cache,id=pnpm,target=/pnpm/store \
    pnpm install --frozen-lockfile

FROM base AS dev
COPY pnpm-workspace.yaml pnpm-lock.yaml* ./
COPY web/package.json web/package.json
RUN --mount=type=cache,id=pnpm,target=/pnpm/store pnpm install --frozen-lockfile
COPY web/ web/
WORKDIR /app/web
EXPOSE 5173
CMD ["pnpm", "dev", "--host", "0.0.0.0", "--port", "5173"]

FROM base AS build
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
