# web

SvelteKit 2 + Svelte 5 (runes) client. See [AGENTS.md](AGENTS.md) for layout and rules, and the
repo root [README.md](../README.md) for the quick start (Docker via `make up`, or native via
`mise` — `docs/infra.md §2`).

Scaffolded with `sv create`:

```sh
pnpm dlx sv@0.17.0 create --template minimal --types ts \
  --add prettier eslint vitest="usages:unit" playwright sveltekit-adapter="adapter:node" \
  --install pnpm web
```
