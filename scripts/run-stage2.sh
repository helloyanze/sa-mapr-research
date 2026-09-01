#!/usr/bin/env bash
set -euo pipefail

phase="${1:-}"
case "${phase}" in
  prepare|preflight|full|resume) ;;
  *)
    echo "Usage: $0 {prepare|preflight|full|resume}" >&2
    exit 2
    ;;
esac

repo_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
"${repo_root}/scripts/run-in-container.sh" \
  bash -lc "cd /workspace/experiments/stage2-v2.1.1 && ./run.sh ${phase}"
