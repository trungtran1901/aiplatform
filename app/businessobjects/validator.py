"""Safe, restricted evaluator for Business Object `payload.validation`
rule strings (e.g. "days > 0", "endDate >= startDate").

Deliberately NOT a general `eval()` - only comparison operators over
plain values (numbers, ISO date strings, booleans) already present in
the submitted record dict are permitted. No function calls, no
attribute access, no imports, no builtins - a bad/malicious rule string
can only ever fail to parse or evaluate to False, never execute
arbitrary code.
"""
from __future__ import annotations

import ast
import operator
from datetime import date, datetime
from typing import Any

_ALLOWED_COMPARISONS = {
    ast.Gt: operator.gt,
    ast.GtE: operator.ge,
    ast.Lt: operator.lt,
    ast.LtE: operator.le,
    ast.Eq: operator.eq,
    ast.NotEq: operator.ne,
}
_ALLOWED_BOOLOPS = {ast.And: all, ast.Or: any}


class RuleEvaluationError(Exception):
    pass


def _coerce(value: Any) -> Any:
    if isinstance(value, str):
        try:
            return datetime.fromisoformat(value).date()
        except ValueError:
            return value
    return value


def _eval_node(node: ast.AST, record: dict) -> Any:
    if isinstance(node, ast.Expression):
        return _eval_node(node.body, record)
    if isinstance(node, ast.Constant):
        return node.value
    if isinstance(node, ast.Name):
        if node.id not in record:
            raise RuleEvaluationError(f"Unknown field referenced in rule: '{node.id}'")
        return _coerce(record[node.id])
    if isinstance(node, ast.Compare):
        left = _eval_node(node.left, record)
        result = True
        for op, comparator in zip(node.ops, node.comparators):
            op_type = type(op)
            if op_type not in _ALLOWED_COMPARISONS:
                raise RuleEvaluationError(f"Unsupported comparison operator: {op_type.__name__}")
            right = _eval_node(comparator, record)
            result = result and _ALLOWED_COMPARISONS[op_type](left, right)
            left = right
        return result
    if isinstance(node, ast.BoolOp):
        op_type = type(node.op)
        if op_type not in _ALLOWED_BOOLOPS:
            raise RuleEvaluationError(f"Unsupported boolean operator: {op_type.__name__}")
        values = [_eval_node(v, record) for v in node.values]
        return _ALLOWED_BOOLOPS[op_type](values)
    if isinstance(node, ast.UnaryOp) and isinstance(node.op, ast.Not):
        return not _eval_node(node.operand, record)
    raise RuleEvaluationError(f"Unsupported expression node: {type(node).__name__}")


def evaluate_rule(rule: str, record: dict) -> bool:
    """Evaluates one restricted boolean rule string against `record`.
    Raises RuleEvaluationError on anything outside the allowed grammar
    (comparisons, and/or/not, literal constants, field-name lookups) -
    callers should catch this and surface it as a validation warning
    rather than letting a malformed rule crash the caller."""
    try:
        tree = ast.parse(rule, mode="eval")
    except SyntaxError as exc:
        raise RuleEvaluationError(f"Could not parse rule '{rule}': {exc}") from exc
    return bool(_eval_node(tree, record))


def validate_record(payload: dict, record: dict) -> list[str]:
    """Runs every rule in payload.get("validation", []) against `record`,
    plus a basic required-fields check from payload.get("fields", []).
    Returns a list of human-readable violation messages (empty list =
    valid). Never raises for a malformed rule - it's reported as a
    violation message instead, so one bad rule in the registry can never
    break every validation call."""
    violations: list[str] = []

    for field in payload.get("fields", []):
        if field.get("required") and record.get(field["name"]) in (None, ""):
            violations.append(f"Field '{field['name']}' is required but missing.")

    for rule_def in payload.get("validation", []):
        rule = rule_def.get("rule")
        message = rule_def.get("message", f"Validation failed: {rule}")
        if not rule:
            continue
        try:
            if not evaluate_rule(rule, record):
                violations.append(message)
        except RuleEvaluationError as exc:
            violations.append(f"Could not evaluate rule '{rule}': {exc}")

    return violations