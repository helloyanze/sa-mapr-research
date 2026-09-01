#!/usr/bin/env bash
set -euo pipefail

repo_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
catalog="${repo_root}/artifacts/artifact-catalog.json"
cache="${repo_root}/artifacts/cache"
image="${SAMAPR_IMAGE:-samapr-runtime:ubuntu24.04}"

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

docker build --pull --tag "${image}" --file "${repo_root}/infra/docker/Dockerfile" "${repo_root}"
echo "Built ${image}"
