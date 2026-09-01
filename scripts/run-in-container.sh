#!/usr/bin/env bash
set -euo pipefail

if [[ $# -eq 0 ]]; then
  echo "Usage: $0 <command> [args...]" >&2
  exit 2
fi

repo_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
data_root="${SAMAPR_DATA_ROOT:-${HOME}/samapr-data}"
image="${SAMAPR_IMAGE:-samapr-runtime:ubuntu24.04}"

mkdir -p \
  "${data_root}/container-home" \
  "${data_root}/stage2/work" \
  "${data_root}/stage2/legacy-outputs" \
  "${data_root}/stage2/runs" \
  "${data_root}/stage2/protocol-locks" \
  "${data_root}/analysis/stage2-correctness"

docker_args=(
  run --rm --init
  --user "$(id -u):$(id -g)"
  --env HOME=/home/samapr
  --env TZ=America/Los_Angeles
  --mount "type=bind,src=${repo_root},dst=/workspace"
  --mount "type=bind,src=${data_root}/container-home,dst=/home/samapr"
  --mount "type=bind,src=${data_root}/stage2/work,dst=/workspace/experiments/stage2-v2.1.1/work"
  --mount "type=bind,src=${data_root}/stage2/legacy-outputs,dst=/workspace/experiments/stage2-v2.1.1/outputs"
  --mount "type=bind,src=${data_root}/stage2/runs,dst=/workspace/experiments/stage2-v2.1.1/outputs_revised_mve"
  --mount "type=bind,src=${data_root}/stage2/protocol-locks,dst=/workspace/experiments/stage2-v2.1.1/protocol_locks"
  --mount "type=bind,src=${data_root}/analysis/stage2-correctness,dst=/workspace/analyses/stage2-correctness/analysis_output"
)

if [[ -f "${repo_root}/.env" ]]; then
  docker_args+=(--env-file "${repo_root}/.env")
fi
if [[ -n "${RUN_ID:-}" ]]; then
  docker_args+=(--env "RUN_ID=${RUN_ID}")
fi

docker "${docker_args[@]}" "${image}" "$@"
