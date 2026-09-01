#!/usr/bin/env python3
from __future__ import annotations

import argparse
import os
import re
import subprocess
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_MAX_FILE = 5 * 1024 * 1024
DEFAULT_MAX_TOTAL = 20 * 1024 * 1024
BANNED_SUFFIXES = {".zip", ".tar", ".tgz", ".gz", ".jar", ".class", ".log", ".docx", ".pdf"}
BANNED_PARTS = {
    "__pycache__", ".venv", "target", "work", "outputs", "outputs_archive",
    "outputs_revised", "outputs_revised_mve", "protocol_locks", "responses",
    "stage2_logs", "spotbugs_reports", "artifacts/cache", "artifacts/downloads",
}
SECRET_PATTERN = re.compile(r"(?im)^\s*(?:LLM_API_KEY|OPENAI_API_KEY)\s*=\s*([^\s#].+)$")


def git_paths(staged: bool) -> list[Path]:
    if staged:
        cmd = ["git", "diff", "--cached", "--name-only", "--diff-filter=ACMR", "-z"]
    else:
        cmd = ["git", "ls-files", "--cached", "--others", "--exclude-standard", "-z"]
    result = subprocess.run(cmd, cwd=ROOT, check=True, capture_output=True)
    return [Path(item.decode("utf-8")) for item in result.stdout.split(b"\0") if item]


def is_banned(path: Path) -> str | None:
    normalized = path.as_posix()
    if path.name == ".env" or (path.name.startswith(".env.") and path.name != ".env.example"):
        return "secret environment file"
    if path.suffix.lower() in BANNED_SUFFIXES:
        return f"banned generated/archive suffix {path.suffix.lower()}"
    for part in BANNED_PARTS:
        if part in normalized.split("/") or f"/{part}/" in f"/{normalized}/":
            return f"runtime/build directory {part}"
    return None


def main() -> int:
    parser = argparse.ArgumentParser(description="Prevent large or sensitive files from entering Git")
    parser.add_argument("--staged", action="store_true", help="check only staged additions and modifications")
    parser.add_argument("--max-file-mib", type=int, default=5)
    parser.add_argument("--max-total-mib", type=int, default=20)
    args = parser.parse_args()
    max_file = args.max_file_mib * 1024 * 1024
    max_total = args.max_total_mib * 1024 * 1024

    problems: list[str] = []
    total = 0
    for relative in git_paths(args.staged):
        path = ROOT / relative
        if not path.is_file():
            continue
        reason = is_banned(relative)
        if reason:
            problems.append(f"{relative.as_posix()}: {reason}")
        size = path.stat().st_size
        total += size
        if size > max_file:
            problems.append(f"{relative.as_posix()}: {size} bytes exceeds {max_file} bytes")
        if size <= 1024 * 1024 and path.suffix.lower() in {"", ".txt", ".md", ".sh", ".py", ".json", ".yaml", ".yml"}:
            try:
                content = path.read_text(encoding="utf-8")
            except UnicodeDecodeError:
                continue
            match = SECRET_PATTERN.search(content)
            if match and match.group(1).strip() not in {"...", "<redacted>", "your-key"}:
                problems.append(f"{relative.as_posix()}: possible API key assignment")

    if args.staged and total > max_total:
        problems.append(f"staged payload: {total} bytes exceeds {max_total} bytes")
    if problems:
        print("REPOSITORY_PAYLOAD_HOLD", file=sys.stderr)
        for problem in problems:
            print(f"- {problem}", file=sys.stderr)
        return 1
    print(f"REPOSITORY_PAYLOAD_PASS files={len(git_paths(args.staged))} bytes={total}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
