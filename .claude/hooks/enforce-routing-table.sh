#!/usr/bin/env bash
# enforces CLAUDE.md's "Context triggers" table: blocks Edit/Write on server/**, web/**,
# and infra files (Dockerfile*, docker-compose*.yml, Makefile) until the matching docs
# have been Read earlier in this session.
set -euo pipefail

input=$(cat)

tool_name=$(jq -r '.tool_name // empty' <<<"$input")
if [[ "$tool_name" != "Edit" && "$tool_name" != "Write" ]]; then
  exit 0
fi

file_path=$(jq -r '.tool_input.file_path // .tool_input.path // empty' <<<"$input")
transcript_path=$(jq -r '.transcript_path // empty' <<<"$input")

if [[ -z "$file_path" ]]; then
  exit 0
fi

project_dir="${CLAUDE_PROJECT_DIR:-/home/michaels/Desktop/mahjong}"

rel_path="$file_path"
case "$file_path" in
  "$project_dir"/*)
    rel_path="${file_path#"$project_dir"/}"
    ;;
esac

base=$(basename -- "$rel_path")

required=()
case "$base" in
  Dockerfile|Dockerfile.*|docker-compose*.yml|Makefile)
    required=("docs/07-infra.md")
    ;;
  *)
    case "$rel_path" in
      server/AGENTS.md) ;;
      server/*)
        required=("server/AGENTS.md" "docs/00-architecture.md")
        ;;
      web/AGENTS.md) ;;
      web/*)
        required=("web/AGENTS.md" "docs/03-frontend.md")
        ;;
    esac
    ;;
esac

if [[ ${#required[@]} -eq 0 ]]; then
  exit 0
fi

read_files=""
if [[ -n "$transcript_path" && -f "$transcript_path" ]]; then
  read_files=$(jq -r '
    select(.type=="assistant") | .message.content[]? |
    select(.type=="tool_use" and .name=="Read") |
    (.input.file_path // .input.path // empty)
  ' "$transcript_path" 2>/dev/null || true)
fi

missing=()
for doc in "${required[@]}"; do
  abs_doc="$project_dir/$doc"
  if ! grep -qxF "$abs_doc" <<<"$read_files"; then
    missing+=("$doc")
  fi
done

if [[ ${#missing[@]} -gt 0 ]]; then
  missing_list=$(printf '%s, ' "${missing[@]}")
  missing_list="${missing_list%, }"
  reason="CLAUDE.md context-triggers table: read ${missing_list} before editing ${rel_path}."
  jq -n --arg reason "$reason" '{
    hookSpecificOutput: {
      hookEventName: "PreToolUse",
      permissionDecision: "deny",
      permissionDecisionReason: $reason
    }
  }'
fi

exit 0
