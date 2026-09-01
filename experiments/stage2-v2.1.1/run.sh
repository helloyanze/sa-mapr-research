#!/usr/bin/env bash
set -euo pipefail

phase="${1:-}"
case "${phase}" in
  prepare|preflight|full|resume) ;;
  *) echo "Usage: $0 {prepare|preflight|full|resume}" >&2; exit 2 ;;
esac

experiment_root="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "${experiment_root}"

git config --global --add safe.directory "$(git rev-parse --show-toplevel)" >/dev/null 2>&1 || true
if [[ -n "$(git status --porcelain --untracked-files=no)" ]]; then
  echo "Tracked files are modified. Commit or stash code before creating a protocol lock." >&2
  exit 1
fi

run_id="${RUN_ID:-stage2_mve_$(date +%Y%m%dT%H%M%S)}"
lock_path="protocol_locks/stage2_protocol_lock.json"
config="config/stage2_v2_1_20bug_config.json"
output="outputs_revised_mve/${run_id}"

mkdir -p protocol_locks outputs outputs_revised_mve work
mvn -q -f tools/javaparser-checker/pom.xml package
python -m unittest discover -s tests -q

if [[ ! -f "${lock_path}" ]]; then
  python scripts/stage2_protocol_lock.py \
    --config "${config}" \
    --output "${lock_path}" \
    --hotfix-gate protocol/legacy_mapping_hotfix_gate.json
fi
python scripts/stage2_protocol_lock.py --config "${config}" --output "${lock_path}" --verify

prepare() {
  python scripts/revised_mve_runner.py --config "${config}" --run-id "${run_id}" --prepare-only
}

preflight() {
  [[ -n "${LLM_API_KEY:-}" ]] || { echo "LLM_API_KEY is required for preflight." >&2; exit 1; }
  prepare
  python scripts/preflight_check.py \
    --config config/stage2_v2_1_config.json \
    --output-root "${output}" \
    --reuse-work
}

case "${phase}" in
  prepare)
    prepare
    ;;
  preflight)
    preflight
    ;;
  full)
    preflight
    python scripts/revised_mve_runner.py --config "${config}" --run-id "${run_id}" --resume
    ;;
  resume)
    [[ -n "${RUN_ID:-}" ]] || { echo "Set RUN_ID to the existing run before resume." >&2; exit 1; }
    [[ -n "${LLM_API_KEY:-}" ]] || { echo "LLM_API_KEY is required for resume." >&2; exit 1; }
    python scripts/revised_mve_runner.py --config "${config}" --run-id "${run_id}" --resume
    ;;
esac

echo "RUN_ID=${run_id}"
