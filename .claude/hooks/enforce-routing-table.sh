#!/usr/bin/env bash
# enforces AGENTS.md's "Context triggers" table: blocks writes to server/**, web/**,
# shared/**, and infra files (Dockerfile*, docker-compose*.yml, Makefile, mise.toml) until the
# matching docs have been referenced earlier in this session.
#
# "Referenced" = the doc's relative path shows up in the input of any prior Read,
# Bash, ctx_execute_file, or Agent call in this transcript — not just a Read tool_use.
# The old version only counted a literal Read, which every default-mode/global-CLAUDE.md
# instruction in this environment steers the model away from (Bash cat/sed, ctx_execute_file,
# auto-mode's "prefer Bash" nudge) — so it denied edits after docs had, in fact, been read.
#
# Mutation detection also covers Bash: `sed -i`, heredocs, `>`/`>>`, `tee`, `cp`/`mv` into a
# guarded path all bypassed the old Edit|Write-only matcher. Serena edit tools are routed too.
#
# separately, AGENTS.md "No script edits": Bash in-place edits of repo source (python/node
# write calls, sed -i, perl -i) are denied regardless of docs read. redirects are left to the
# docs check only: `git show … > path`, generators and `tee` logs are legitimate.
set -euo pipefail

input=$(cat)

tool_name=$(jq -r '.tool_name // empty' <<<"$input")
transcript_path=$(jq -r '.transcript_path // empty' <<<"$input")

project_dir="${CLAUDE_PROJECT_DIR:-}"
if [[ -z "$project_dir" ]]; then
  project_dir=$(git rev-parse --show-toplevel 2>/dev/null || pwd)
fi

# collect every rel_path this tool call is about to write to.
targets=()

deny() {
  jq -n --arg reason "$1" '{
    hookSpecificOutput: {
      hookEventName: "PreToolUse",
      permissionDecision: "deny",
      permissionDecisionReason: $reason
    }
  }'
  exit 0
}

# repo-ish path prefixes; also catches relative paths after `cd web` (src/, messages/, ...)
repo_path_re='(^|[^A-Za-z0-9_.-])(server|web|shared|docs|ml|src|app|tests|messages|scripts)/'

case "$tool_name" in
  Edit|Write)
    file_path=$(jq -r '.tool_input.file_path // .tool_input.path // empty' <<<"$input")
    [[ -n "$file_path" ]] && targets+=("$file_path")
    ;;
  mcp__serena__replace_symbol_body|mcp__serena__insert_after_symbol|mcp__serena__insert_before_symbol|mcp__serena__replace_content|mcp__serena__rename_symbol|mcp__serena__safe_delete_symbol|mcp__serena__replace_in_files)
    rel=$(jq -r '.tool_input.relative_path // empty' <<<"$input")
    glob=$(jq -r '.tool_input.paths_include_glob // empty' <<<"$input")
    if [[ -n "$rel" ]]; then
      targets+=("$rel")
    elif [[ -n "$glob" ]]; then
      targets+=("$glob")
    else
      # whole-project replace_in_files touches every guarded tree
      targets+=(server/x web/x shared/x)
    fi
    ;;
  Bash)
    command=$(jq -r '.tool_input.command // empty' <<<"$input")
    [[ -z "$command" ]] && exit 0
    # AGENTS.md "No script edits": in-place edits via interpreters/sed/redirects are denied
    # outright for repo source paths, regardless of docs read.
    if grep -qE "$repo_path_re" <<<"$command"; then
      if grep -qE '\bsed +(-[A-Za-z]*i|--in-place)|\bperl +-[A-Za-z]*i' <<<"$command" \
        || { grep -qE '\b(python3?|node|bun|deno)\b' <<<"$command" \
          && grep -qE "open\([^)]*,[[:space:]]*['\"][wax+]|write_text|write_bytes|writeFileSync|writeFile\(|\.write\(" <<<"$command"; }; then
        deny "AGENTS.md 'No script edits': don't modify repo files via python/node/sed -i/perl -i. Use Serena (replace_symbol_body, replace_content, insert_*_symbol; load via ToolSearch) or Read + Edit/Write."
      fi
    fi
    # strip common read-only stderr-discard redirects before checking for a mutation shape,
    # so e.g. `grep ... file 2>/dev/null` doesn't look like a write to `file`.
    sanitized=$(sed -E 's/[0-9]?>&[0-9]|[0-9]?>[[:space:]]*\/dev\/null//g' <<<"$command")
    # only bother if the command looks like it mutates a file at all
    if ! grep -qE 'sed +-i|>>?[^&]|\btee\b|\bcp\b|\bmv\b|<<' <<<"$sanitized"; then
      exit 0
    fi
    # pull path-shaped tokens under server/, web/, shared/, docs/, or known infra filenames
    while IFS= read -r tok; do
      targets+=("$tok")
    done < <(grep -oE '([A-Za-z0-9_./-]*/)?(server|web|shared|docs)/[A-Za-z0-9_./-]+|Dockerfile[A-Za-z0-9._-]*|docker-compose[A-Za-z0-9._-]*\.yml|Makefile|mise\.toml' <<<"$command" || true)
    [[ ${#targets[@]} -eq 0 ]] && exit 0
    ;;
  *)
    exit 0
    ;;
esac

[[ ${#targets[@]} -eq 0 ]] && exit 0

doc_for_target() {
  local t="$1" rel base
  rel="$t"
  case "$t" in
    "$project_dir"/*) rel="${t#"$project_dir"/}" ;;
  esac
  base=$(basename -- "$rel")
  case "$base" in
    Dockerfile|Dockerfile.*|docker-compose*.yml|Makefile|mise.toml)
      echo "docs/infra.md" ;;
    *)
      case "$rel" in
        server/AGENTS.md|web/AGENTS.md) ;;
        server/*) echo "server/AGENTS.md"; echo "docs/architecture.md" ;;
        web/*) echo "web/AGENTS.md"; echo "docs/frontend.md" ;;
        shared/*) echo "docs/protocol.md" ;;
      esac
      ;;
  esac
  # test files additionally route to the testing doc, on top of whatever their
  # path prefix above already required.
  case "$base" in
    *.spec.ts|*.test.ts) echo "docs/testing.md" ;;
  esac
}

required=()
for t in "${targets[@]}"; do
  while IFS= read -r doc; do
    [[ -n "$doc" ]] && required+=("$doc")
  done < <(doc_for_target "$t")
done

[[ ${#required[@]} -eq 0 ]] && exit 0
# dedupe (macOS ships bash 3.2 — no mapfile/readarray)
required_dedup=()
while IFS= read -r doc; do
  required_dedup+=("$doc")
done < <(printf '%s\n' "${required[@]}" | sort -u)
required=("${required_dedup[@]}")

# build a blob of everything this session has referenced a path/command/prompt in
refs=""
# copilot CLI passes sessionId but no transcript_path; fall back to its session events log,
# which records tools as assistant.message events with lowercase names and `arguments`.
if [[ -z "$transcript_path" || ! -f "$transcript_path" ]]; then
  session_id=$(jq -r '.session_id // .sessionId // empty' <<<"$input")
  candidate="$HOME/.copilot/session-state/$session_id/events.jsonl"
  [[ -n "$session_id" && -f "$candidate" ]] && transcript_path="$candidate"
fi
if [[ -n "$transcript_path" && -f "$transcript_path" ]]; then
  refs=$(jq -r '
    (select(.type=="assistant") | .message.content[]? |
      select(.type=="tool_use" and (.name=="Read" or .name=="Bash" or .name=="ctx_execute_file" or .name=="Agent" or (.name | test("ctx_execute_file$")))) |
      [.input.file_path, .input.path, .input.command, .input.prompt] | .[] | select(. != null)),
    (select(.type=="assistant.message") | .data.toolRequests[]? |
      select((.name | IN("read", "view", "bash", "grep", "task", "agent")) or (.name | test("ctx_execute_file$"))) |
      [.arguments.file_path, .arguments.path, .arguments.command, .arguments.prompt] | .[] | select(. != null))
  ' "$transcript_path" 2>/dev/null || true)
fi

missing=()
for doc in "${required[@]}"; do
  if ! grep -qF "$doc" <<<"$refs"; then
    missing+=("$doc")
  fi
done

if [[ ${#missing[@]} -gt 0 ]]; then
  missing_list=$(printf '%s, ' "${missing[@]}")
  missing_list="${missing_list%, }"
  target_list=$(printf '%s, ' "${targets[@]}")
  target_list="${target_list%, }"
  deny "AGENTS.md context-triggers table: reference ${missing_list} before writing to ${target_list}."
fi

exit 0
