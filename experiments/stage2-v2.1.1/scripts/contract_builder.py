from __future__ import annotations

import json
from pathlib import Path

from common import safe_rel_path


VERIFICATION_TYPES = [
    ('COMPILE_SUCCESS', 'Defects4JCompiler'),
    ('FAILING_TEST_PASS', 'Defects4JTestRunner'),
    ('ALL_TEST_PASS', 'Defects4JTestRunner'),
    ('TARGET_WARNING_REMOVED', 'SpotBugsDeltaChecker'),
    ('NO_NEW_SAME_WARNING', 'SpotBugsDeltaChecker'),
    ('PUBLIC_API_UNCHANGED', 'JavaParserApiDiff'),
    ('SCOPE_LIMITATION', 'DiffScopeChecker'),
]


def load_registry(root: Path) -> dict:
    return json.loads((root / 'config/obligation_registry.json').read_text(encoding='utf-8'))


def build_contract(item: dict, registry: dict) -> dict:
    evidence = []
    obligations = []
    seen_targets: set[tuple[str, str, str]] = set()
    for warning in item.get('buggy_spotbugs_warnings', []):
        pattern = str(warning['spotbugs_pattern'])
        if pattern not in registry:
            raise ValueError(f"{item['bug_key']}: unregistered SpotBugs pattern {pattern}")
        target = {
            'file': safe_rel_path(warning['target_file']),
            'method': str(warning.get('target_method', '')),
        }
        evidence.append({
            'source': 'SpotBugs_buggy_version',
            'pattern': pattern,
            'category': str(warning.get('spotbugs_category', '')),
            'message': str(warning.get('message', '')),
            'priority': str(warning.get('priority', '')),
            'rank': str(warning.get('rank', '')),
            'location': {
                **target,
                'start_line': str(warning.get('start_line', '')),
                'end_line': str(warning.get('end_line', '')),
            },
        })
        spec = registry[pattern]
        signature = (spec['type'], target['file'], target['method'])
        if signature in seen_targets:
            continue
        seen_targets.add(signature)
        obligations.append({
            'id': f'O{len(obligations)+1}',
            'type': spec['type'],
            'checkability': 'M_AST',
            'severity': 'blocking',
            'target': target,
            'checker': 'JavaParserPatternMatcher',
            'expected_ast_nodes': list(spec.get('expected_ast_nodes', [])),
            'source_regex': str(spec.get('source_regex', '')),
            'failure_policy': 'reject',
            'description': f'Satisfy the {spec["type"]} obligation induced by buggy-version {pattern}.',
        })
    primary = {'file': safe_rel_path(item['target_file']), 'method': str(item.get('target_method', ''))}
    for typ, desc in [
        ('PUBLIC_API_UNCHANGED', 'Do not change public or protected API signatures.'),
        ('SCOPE_LIMITATION', 'Modify only Contract-declared source targets and minimum necessary code regions.'),
    ]:
        obligations.append({
            'id': f'O{len(obligations)+1}', 'type': typ, 'checkability': 'M_AST',
            'severity': 'blocking', 'target': primary, 'checker': 'HybridVerifier',
            'failure_policy': 'reject', 'description': desc,
        })
    verification = [
        {'id': f'V{i}', 'type': typ, 'checkability': 'M_TOOL' if i <= 5 else 'M_AST',
         'checker': checker, 'severity': 'blocking', 'failure_policy': 'reject'}
        for i, (typ, checker) in enumerate(VERIFICATION_TYPES, 1)
    ]
    return {
        'contract_id': f"C-{item['bug_key']}-001",
        'bug_key': item['bug_key'],
        'static_evidence': evidence,
        'repair_obligations': obligations,
        'verification_obligations': verification,
        'non_regression_constraints': [
            'Do not modify tests.',
            'Do not change public or protected API signatures.',
            'Do not edit files outside Contract-declared source targets.',
            'Do not suppress SpotBugs warnings instead of correcting behavior.',
        ],
        'acceptance_criteria': [
            'Patch applies cleanly.', 'Project compiles.', 'Trigger tests pass.', 'All tests pass.',
            'Target SpotBugs warning is removed.', 'No new same-pattern warning is introduced.',
            'Public/protected API is unchanged.', 'Patch stays within allowed scope.',
        ],
    }


def validate_contract(contract: dict, schema_path: Path) -> None:
    try:
        import jsonschema
    except ImportError as exc:
        raise RuntimeError('Python dependency jsonschema is required for Contract validation') from exc
    schema = json.loads(schema_path.read_text(encoding='utf-8'))
    jsonschema.validate(contract, schema)


def allowed_source_files(contract: dict) -> list[str]:
    files = []
    for section in ('static_evidence', 'repair_obligations'):
        for entry in contract.get(section, []):
            target = entry.get('location', {}) if section == 'static_evidence' else entry.get('target', {})
            value = target.get('file')
            if value:
                files.append(safe_rel_path(value))
    return list(dict.fromkeys(files))
