#!/usr/bin/env bash
set -euo pipefail

root_dir="$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)"
output="${1:-sub2api-admin-skill.tar.gz}"
case "$output" in
  /*) output_path="$output" ;;
  *) output_path="$PWD/$output" ;;
esac

tar -czf "$output_path" \
  --exclude='__pycache__' \
  --exclude='*.pyc' \
  -C "$(dirname -- "$root_dir")" "$(basename -- "$root_dir")"
printf '%s\n' "$output_path"
