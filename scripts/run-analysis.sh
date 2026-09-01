#!/usr/bin/env bash
set -euo pipefail

phase="${1:-validate}"
repo_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"

case "${phase}" in
  validate)
    command="python scripts/validate_inputs.py"
    ;;
  full)
    command="python scripts/validate_inputs.py && python scripts/analyze.py"
    ;;
  *)
    echo "Usage: $0 {validate|full}" >&2
    exit 2
    ;;
esac

"${repo_root}/scripts/run-in-container.sh" \
  bash -lc "cd /workspace/analyses/stage2-correctness && ${command}"
