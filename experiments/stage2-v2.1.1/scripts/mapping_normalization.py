from __future__ import annotations

import re
from pathlib import Path
from typing import Iterable


_LINE_RE = re.compile(r"\bline\s*[:#]?\s*(\d+)\b", re.IGNORECASE)
_SOURCE_PREFIXES = (
    "src/main/java/",
    "src/java/",
    "source/",
    "src/",
)


def _text(value) -> str:
    return "" if value is None else str(value).strip().strip("`\"'")


def normalize_file(value, repository_files: Iterable[str] = (), checkout_root=None) -> str:
    """Return a stable repository-relative Java path.

    Known repository paths win over source-root heuristics.  This makes absolute
    checkout paths, Defects4J's ``source/`` paths, and Windows paths converge on
    the exact path stored in the contract.
    """
    raw = _text(value).replace("\\", "/")
    raw = re.sub(r"^file:(?://)?", "", raw, flags=re.IGNORECASE)
    raw = re.sub(r"^[ab]/", "", raw)
    raw = re.sub(r"\s+", " ", raw).strip()
    if checkout_root:
        root = str(Path(checkout_root)).replace("\\", "/").rstrip("/")
        if raw.lower().startswith(root.lower() + "/"):
            raw = raw[len(root) + 1 :]

    known = [str(item).replace("\\", "/").lstrip("./") for item in repository_files]
    suffix_matches = [item for item in known if raw == item or raw.lower().endswith("/" + item.lower())]
    if len(suffix_matches) == 1:
        return suffix_matches[0]

    lowered = raw.lower()
    for prefix in _SOURCE_PREFIXES:
        marker = "/" + prefix
        index = lowered.rfind(marker)
        if index >= 0:
            raw = raw[index + len(marker) :]
            break
        if lowered.startswith(prefix):
            raw = raw[len(prefix) :]
            break
    return raw.lstrip("/")


def _split_parameters(value: str) -> list[str]:
    if not value.strip():
        return []
    parts, current, depth = [], [], 0
    for char in value:
        if char in "<([":
            depth += 1
        elif char in ">)]" and depth:
            depth -= 1
        if char == "," and depth == 0:
            parts.append("".join(current))
            current = []
        else:
            current.append(char)
    parts.append("".join(current))
    return parts


def _normalize_type(value: str) -> str:
    value = re.sub(r"@[\w.]+(?:\([^)]*\))?\s*", "", value.strip())
    value = re.sub(r"\b(?:final|volatile|transient)\b\s*", "", value)
    value = value.replace("...", "[]")
    # Drop a parameter variable name while keeping a lone simple type intact.
    variable = re.match(r"^(.*(?:>|\]|\w))\s+([A-Za-z_$][\w$]*)$", value)
    if variable and not variable.group(1).rstrip().endswith(("extends", "super")):
        value = variable.group(1)
    # Qualified and simple Java types are compared using the same simple name.
    value = re.sub(r"\b(?:[a-z_$][\w$]*\.)+([A-Z_$][\w$]*)", r"\1", value)
    value = re.sub(r"\s+", "", value)
    return value


def normalize_method_signature(value, declaring_class: str | None = None) -> str:
    """Canonicalize Java method display formats without collapsing overloads."""
    raw = _text(value)
    raw = _LINE_RE.sub("", raw)
    raw = re.sub(r"\bmethod\b", "", raw, flags=re.IGNORECASE).strip(" ,;:")
    qualifier = ""
    if "::" in raw:
        qualifier, raw = raw.rsplit("::", 1)
    open_paren = raw.find("(")
    if open_paren >= 0:
        prefix, suffix = raw[:open_paren], raw[open_paren:]
        if "." in prefix:
            qualifier, prefix = prefix.rsplit(".", 1)
        raw = prefix + suffix
    match = re.fullmatch(r"([A-Za-z_$<>][\w$<>]*)\s*(?:\((.*)\))?", raw.strip())
    if not match:
        return ""
    name, parameters = match.group(1), match.group(2)
    class_name = _text(declaring_class) or qualifier.rsplit(".", 1)[-1]
    if name == "<init>" or (class_name and name == class_name):
        name = "<init>"
    if parameters is None:
        return name
    normalized = [_normalize_type(item) for item in _split_parameters(parameters)]
    if any(not item for item in normalized):
        return ""
    return f"{name}({','.join(normalized)})"


def normalize_symbol(value) -> str | None:
    raw = _text(value)
    if not raw or raw.lower() in {"null", "none", "n/a", "not_applicable"}:
        return None
    raw = raw.rsplit("::", 1)[-1].rsplit(".", 1)[-1]
    return re.sub(r"\s+", "", raw) or None


def normalize_change_type(value) -> str | None:
    raw = re.sub(r"[\s_-]+", "", _text(value).lower())
    if not raw or raw in {"null", "none", "na", "notapplicable"}:
        return None
    aliases = {
        "modified": "modify",
        "modification": "modify",
        "changed": "modify",
        "change": "modify",
        "updated": "modify",
        "added": "add",
        "addition": "add",
        "inserted": "add",
        "removed": "remove",
        "deleted": "remove",
        "deletion": "remove",
        "renamed": "rename",
    }
    return aliases.get(raw, raw)


def _contract_targets(contract: dict) -> dict[str, dict]:
    anchors = {item.get("id"): item for item in contract.get("evidence_anchor", [])}
    targets = {}
    for obligation in contract.get("repair_obligations", []):
        anchor = anchors.get(obligation.get("evidence_anchor_id"), {})
        targets[str(obligation.get("id", ""))] = {
            "file": anchor.get("file", ""),
            "method_signature": anchor.get("method", ""),
            "symbol": None,
            "change_type": None,
        }
    return targets


def _location_parts(location, repository_files) -> tuple[str, str, int | None]:
    raw = _text(location)
    line_match = _LINE_RE.search(raw)
    line = int(line_match.group(1)) if line_match else None
    java_end = raw.lower().find(".java")
    if java_end < 0:
        return "", "", line
    java_end += len(".java")
    file_part = raw[:java_end]
    suffix = raw[java_end:].strip()
    if suffix.startswith("::"):
        suffix = suffix[2:]
    else:
        suffix = suffix.lstrip(" ,;:")
    suffix = _LINE_RE.sub("", suffix)
    suffix = re.sub(r"(?:[,;:]\s*)+$", "", suffix).strip()
    suffix = re.sub(r"\bmethod\b", "", suffix, flags=re.IGNORECASE).strip(" ,;:")
    return normalize_file(file_part, repository_files), normalize_method_signature(suffix), line


def canonicalize_claimed_mappings(contract: dict, claimed) -> list[dict]:
    repository_files = contract.get("hard_repair_scope", {}).get("allowed_source_files", [])
    defaults = _contract_targets(contract)
    rows = []
    if not isinstance(claimed, list):
        return rows
    for entry in claimed:
        if not isinstance(entry, dict):
            rows.append({"obligation_id": "", "target": {}, "change_type": None, "auxiliary": {},
                         "valid": False, "problems": ["mapping entry is not object"], "provenance": {}})
            continue
        oid = _text(entry.get("obligation_id"))
        default = defaults.get(oid, {})
        structured = entry.get("target") if isinstance(entry.get("target"), dict) else {}
        file_value = structured.get("file", entry.get("file", ""))
        method_value = structured.get("method_signature", entry.get("method_signature", ""))
        symbol_value = structured.get("symbol", entry.get("symbol"))
        change_value = entry.get("change_type", structured.get("change_type"))
        line = entry.get("line")
        location_file = location_method = ""
        location_line = None
        if entry.get("patch_location"):
            location_file, location_method, location_line = _location_parts(entry.get("patch_location"), repository_files)
        file_name = normalize_file(file_value, repository_files) if file_value else location_file
        method = normalize_method_signature(method_value, Path(file_name).stem if file_name else None) if method_value else location_method
        inferred = False
        if not method and file_name and normalize_file(default.get("file", ""), repository_files) == file_name:
            method = normalize_method_signature(default.get("method_signature", ""), Path(file_name).stem)
            inferred = bool(method)
        normalized_line = line if isinstance(line, int) else location_line
        problems = []
        if oid not in defaults:
            problems.append("unknown obligation_id")
        if not file_name or not file_name.lower().endswith(".java"):
            problems.append("missing or malformed target file")
        if not method:
            problems.append("missing or malformed method signature")
        target = {
            "file": file_name,
            "method_signature": method,
            "symbol": normalize_symbol(symbol_value),
        }
        rows.append({
            "obligation_id": oid,
            "target": target,
            "change_type": normalize_change_type(change_value),
            "auxiliary": {"line": normalized_line},
            "valid": not problems,
            "problems": problems,
            "provenance": {
                "original_patch_location": entry.get("patch_location"),
                "method_inferred_from_contract_anchor": inferred,
            },
        })
    return rows


def canonicalize_realized_mappings(contract: dict, realized) -> list[dict]:
    repository_files = contract.get("hard_repair_scope", {}).get("allowed_source_files", [])
    rows = []
    for entry in realized if isinstance(realized, list) else []:
        oid = _text(entry.get("obligation_id")) if isinstance(entry, dict) else ""
        candidates = []
        structured_targets = entry.get("actual_patch_targets", []) if isinstance(entry, dict) else []
        if structured_targets:
            for target in structured_targets:
                file_name = normalize_file(target.get("file", ""), repository_files)
                candidates.append({
                    "file": file_name,
                    "method_signature": normalize_method_signature(target.get("method_signature", ""), Path(file_name).stem),
                    "symbol": normalize_symbol(target.get("symbol")),
                    "change_type": normalize_change_type(target.get("change_type")),
                })
        elif isinstance(entry, dict):
            for location in entry.get("actual_patch_locations", []):
                file_name, method, _ = _location_parts(location, repository_files)
                candidates.append({"file": file_name, "method_signature": method, "symbol": None, "change_type": None})
        valid_targets = [target for target in candidates if target["file"] and target["method_signature"]]
        problems = [] if len(valid_targets) == len(candidates) else ["malformed realized target"]
        rows.append({
            "obligation_id": oid,
            "targets": valid_targets,
            "realized": bool(entry.get("realized")) if isinstance(entry, dict) else False,
            "mappable": bool(valid_targets),
            "problems": problems,
        })
    return rows


def _method_name(signature: str) -> str:
    return signature.split("(", 1)[0]


def _target_match(claim: dict, actual: dict, same_name_candidates: int) -> tuple[bool, bool, list[str]]:
    reasons = []
    file_ok = claim.get("file") == actual.get("file")
    if not file_ok:
        reasons.append("different normalized file")
    claim_method, actual_method = claim.get("method_signature", ""), actual.get("method_signature", "")
    method_exact = claim_method == actual_method
    if method_exact:
        method_ok = True
    elif "(" not in claim_method and _method_name(claim_method) == _method_name(actual_method):
        method_ok = same_name_candidates == 1
        if not method_ok:
            reasons.append("under-specified method is ambiguous across overloads")
    else:
        method_ok = False
        reasons.append("different normalized method signature")
    optional_exact = True
    for field in ("symbol", "change_type"):
        claimed_value, actual_value = claim.get(field), actual.get(field)
        if claimed_value is None:
            continue
        if claimed_value is not None and actual_value is not None and claimed_value != actual_value:
            reasons.append(f"different normalized {field}")
            return False, False, reasons
        if actual_value is None:
            optional_exact = False
    matched = file_ok and method_ok
    exact = matched and method_exact and optional_exact
    return matched, exact, reasons


def compare_canonical_mappings(contract: dict, claimed_rows: list[dict], realized_rows: list[dict]) -> dict:
    valid_ids = {str(item.get("id", "")) for item in contract.get("repair_obligations", [])}
    claims = {row.get("obligation_id"): row for row in claimed_rows if row.get("obligation_id") in valid_ids}
    realized_by = {row.get("obligation_id"): row for row in realized_rows if row.get("obligation_id") in valid_ids}
    entries = []
    for oid in sorted(valid_ids):
        claim = claims.get(oid)
        actual_row = realized_by.get(oid, {"targets": [], "realized": False, "mappable": False})
        targets = actual_row.get("targets", [])
        matched_target = None
        exact = False
        reasons = []
        if not claim:
            reasons.append("missing claimed mapping")
        elif not claim.get("valid"):
            reasons.extend(claim.get("problems", ["invalid claimed mapping"]))
        elif not targets:
            reasons.append("no realized mappable target")
        else:
            claim_target = {**claim["target"], "change_type": claim.get("change_type")}
            same_name = sum(
                _method_name(target.get("method_signature", "")) == _method_name(claim_target.get("method_signature", ""))
                for target in targets
            )
            candidate_reasons = []
            for target in targets:
                matched, candidate_exact, why = _target_match(claim_target, target, same_name)
                if matched:
                    matched_target, exact = target, candidate_exact
                    reasons = []
                    break
                candidate_reasons.extend(why)
            if matched_target is None:
                reasons = list(dict.fromkeys(candidate_reasons)) or ["no canonical target match"]
        entries.append({
            "obligation_id": oid,
            "claimed": claim,
            "realized": actual_row,
            "confirmed": matched_target is not None,
            "exact": exact,
            "matched_target": matched_target,
            "mismatch_reasons": reasons,
        })
    return {"comparison_basis": "canonical_structured_semantics_v2_1_1", "entries": entries}


def calculate_mapping_metrics(contract: dict, claimed_rows: list[dict], realized_rows: list[dict], comparison: dict,
                              claimed_valid: bool) -> dict:
    valid_ids = {str(item.get("id", "")) for item in contract.get("repair_obligations", [])}
    valid_claims = [row for row in claimed_rows if row.get("valid") and row.get("obligation_id") in valid_ids]
    mappable = [row for row in realized_rows if row.get("mappable") and row.get("obligation_id") in valid_ids]
    confirmed_ids = {row["obligation_id"] for row in comparison["entries"] if row["confirmed"]}
    precision = len(confirmed_ids & {row["obligation_id"] for row in valid_claims}) / len(valid_claims) if valid_claims else 0.0
    coverage = len(confirmed_ids & {row["obligation_id"] for row in mappable}) / len(mappable) if mappable else 0.0
    expected_claim_ids = {row.get("obligation_id") for row in claimed_rows}
    all_semantic = bool(comparison["entries"]) and all(row["confirmed"] for row in comparison["entries"])
    consistent = bool(claimed_valid) and all(row.get("valid") for row in claimed_rows) and expected_claim_ids == valid_ids and all_semantic
    exact = consistent and all(row["exact"] for row in comparison["entries"])
    return {
        "metric_version": "2.1.1",
        "definitions": {
            "mapping_precision": "confirmed claimed mappings / all valid claimed mappings",
            "mapping_coverage": "correctly claimed realized obligations / all realized mappable obligations",
        },
        "claimed_mapping_valid": bool(claimed_valid),
        "realized_mapping_success": bool(realized_rows) and all(row.get("realized") for row in realized_rows),
        "mapping_consistent": consistent,
        "mapping_exact": exact,
        "mapping_precision": round(precision, 6),
        "mapping_coverage": round(coverage, 6),
        "confirmed_claimed_mappings": len(confirmed_ids & {row["obligation_id"] for row in valid_claims}),
        "valid_claimed_mappings": len(valid_claims),
        "covered_realized_obligations": len(confirmed_ids & {row["obligation_id"] for row in mappable}),
        "realized_mappable_obligations": len(mappable),
    }


def replay_mapping(contract: dict, claimed, realized, claimed_valid: bool) -> dict:
    claimed_rows = canonicalize_claimed_mappings(contract, claimed)
    realized_rows = canonicalize_realized_mappings(contract, realized)
    comparison = compare_canonical_mappings(contract, claimed_rows, realized_rows)
    metrics = calculate_mapping_metrics(contract, claimed_rows, realized_rows, comparison, claimed_valid)
    return {"claimed_normalized": claimed_rows, "realized_normalized": realized_rows,
            "comparison": comparison, "metrics": metrics}
