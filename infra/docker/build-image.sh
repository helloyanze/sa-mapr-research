#!/usr/bin/env bash
set -euo pipefail

repo_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
catalog="${repo_root}/artifacts/artifact-catalog.json"
cache="${repo_root}/artifacts/cache"
image="${SAMAPR_IMAGE:-samapr-runtime:ubuntu24.04}"
base_image="ubuntu:24.04"

command -v docker >/dev/null || { echo "docker is not installed or not on PATH" >&2; exit 1; }

python3 - "${catalog}" "${cache}" <<'PY'
import hashlib
import json
import sys
from pathlib import Path

catalog_path = Path(sys.argv[1])
cache = Path(sys.argv[2])
problems = []
for item in json.loads(catalog_path.read_text(encoding="utf-8"))["artifacts"]:
    path = cache / item["name"]
    if not path.is_file():
        problems.append(f"missing: {path}")
        continue
    if path.stat().st_size != item["size_bytes"]:
        problems.append(f"size mismatch: {path}")
        continue
    hasher = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            hasher.update(chunk)
    digest = hasher.hexdigest()
    if digest != item["sha256"]:
        problems.append(f"sha256 mismatch: {path}")
if problems:
    raise SystemExit("Artifact gate failed:\n- " + "\n- ".join(problems))
print("Artifact gate: PASS")
PY

# Pull through the Docker daemon first. Some Docker/BuildKit combinations do not
# inherit the daemon proxy while resolving FROM metadata during `docker build
# --pull`, even though `docker pull` uses it correctly.
docker pull "${base_image}"

daemon_http_proxy="$(docker info --format '{{.HTTPProxy}}' 2>/dev/null || true)"
daemon_https_proxy="$(docker info --format '{{.HTTPSProxy}}' 2>/dev/null || true)"
daemon_no_proxy="$(docker info --format '{{.NoProxy}}' 2>/dev/null || true)"
build_http_proxy="${SAMAPR_BUILD_HTTP_PROXY:-${SAMAPR_BUILD_PROXY:-${daemon_http_proxy}}}"
build_https_proxy="${SAMAPR_BUILD_HTTPS_PROXY:-${SAMAPR_BUILD_PROXY:-${daemon_https_proxy}}}"
build_no_proxy="${SAMAPR_BUILD_NO_PROXY:-${daemon_no_proxy}}"

build_options=(
  --pull=false
  --tag "${image}"
  --file "${repo_root}/infra/docker/Dockerfile"
)

if [[ -n "${build_http_proxy}" || -n "${build_https_proxy}" ]]; then
  build_options+=(--network=host)
  [[ -n "${build_http_proxy}" ]] && build_options+=(--build-arg "HTTP_PROXY=${build_http_proxy}" --build-arg "http_proxy=${build_http_proxy}")
  [[ -n "${build_https_proxy}" ]] && build_options+=(--build-arg "HTTPS_PROXY=${build_https_proxy}" --build-arg "https_proxy=${build_https_proxy}")
  [[ -n "${build_no_proxy}" ]] && build_options+=(--build-arg "NO_PROXY=${build_no_proxy}" --build-arg "no_proxy=${build_no_proxy}")
  echo "Build proxy: enabled"
else
  echo "Build proxy: disabled"
fi

docker build "${build_options[@]}" "${repo_root}"
echo "Built ${image}"
