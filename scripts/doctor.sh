#!/usr/bin/env bash
set -euo pipefail

repo_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
image="${SAMAPR_IMAGE:-samapr-runtime:ubuntu24.04}"

command -v docker >/dev/null || { echo "docker is not installed or not on PATH" >&2; exit 1; }
docker info >/dev/null
docker image inspect "${image}" >/dev/null 2>&1 || {
  echo "Image ${image} is missing. Run ./infra/docker/build-image.sh first." >&2
  exit 1
}

"${repo_root}/scripts/run-in-container.sh" bash -lc '
set -euo pipefail
java -version
mvn -version
python --version
defects4j info -p Lang >/dev/null
spotbugs -version
git config --global --add safe.directory /workspace
cd /workspace/experiments/stage2-v2.1.1
mvn -q -f tools/javaparser-checker/pom.xml package
python -m unittest discover -s tests -q
python scripts/dry_run.py --config config/stage2_config.json
echo "SAMAPR_DOCKER_DOCTOR_PASS"
'
