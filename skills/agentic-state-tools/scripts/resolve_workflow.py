"""Resolve task intent into the smallest safe ordered skill route."""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

HERE = Path(__file__).resolve()
CONFIG_SCRIPTS = HERE.parents[2] / "agentic-configuration" / "scripts"
sys.path.insert(0, str(CONFIG_SCRIPTS))
from load_config import load_config  # noqa: E402
from schema_validation import validate_file  # noqa: E402
from resolve_project_profile import resolve_profile  # noqa: E402
from runtime_utils import sha256_json, write_json_atomic  # noqa: E402

REQUEST_SCHEMA = HERE.parents[1] / "schemas" / "workflow-request.schema.json"
DECISION_SCHEMA = HERE.parents[1] / "schemas" / "workflow-decision.schema.json"

DEPTH_TO_QUALITY = {
    "focused": "focused",
    "standard": "standard",
    "controlled": "strict",
}
QUALITY_ORDER = {"focused": 0, "standard": 1, "strict": 2}
STAGE_OUTPUTS = {
    "brainstorm": "goals, constraints, alternatives, and selected direction",
    "debug": "root-cause hypothesis and reproducible evidence",
    "explore": "repository facts, affected paths, and material unknowns",
    "plan": "bounded plan or task contract",
    "plan_review": "independent plan outcome",
    "implement": "smallest complete in-scope change",
    "configuration": "validated central configuration change",
    "skill_authoring": "skill changes that preserve package conventions",
    "verify": "fresh evidence for the requested outcome",
    "review": "independent review outcome",
    "batch_review": "cross-task or integrated review outcome",
    "recovery": "recovery classification and safe next action",
    "delivery": "approval-backed delivery decision",
}


def _max_depth(order: list[str], *values: str) -> str:
    return max(values, key=order.index)


def _max_quality(*values: str) -> str:
    return max(values, key=QUALITY_ORDER.__getitem__)


def _normalized_request(
    request: dict[str, Any], config: dict[str, Any]
) -> tuple[dict[str, Any], list[str]]:
    if not isinstance(request, dict):
        raise ValueError("workflow request must be an object")
    normalized = dict(request)
    notes: list[str] = []

    legacy_change_type = normalized.pop("change_type", None)
    legacy_full = normalized.pop("explicit_full_workflow", False)
    legacy_delivery = normalized.pop("requires_delivery_action", None)
    if not isinstance(legacy_full, bool):
        raise ValueError("explicit_full_workflow must be boolean")
    if legacy_delivery is not None and not isinstance(legacy_delivery, bool):
        raise ValueError("requires_delivery_action must be boolean")

    route_id = normalized.get("task_route")
    if legacy_change_type is not None:
        if not isinstance(legacy_change_type, str) or not legacy_change_type.strip():
            raise ValueError("change_type must be a non-empty string")
        mapped = config["workflow"]["legacy_change_type_routes"].get(
            legacy_change_type.strip()
        )
        if not mapped:
            raise ValueError(f"unsupported legacy change_type: {legacy_change_type}")
        if route_id is not None and route_id != mapped:
            raise ValueError(
                f"task_route {route_id} conflicts with legacy change_type {legacy_change_type}"
            )
        normalized["task_route"] = mapped
        notes.append(f"legacy change_type {legacy_change_type} mapped to route {mapped}")

    normalized.setdefault("profile", config["default_profile"])
    normalized.setdefault("task_route", "general_change")
    normalized.setdefault("execution_preference", "auto")
    normalized.setdefault("estimated_files", 1)
    normalized.setdefault("concerns", 1)
    normalized.setdefault("risk_flags", [])
    normalized.setdefault("user_requested_review", False)
    normalized.setdefault("delivery_action", "none")

    if legacy_delivery:
        if normalized["delivery_action"] != "none":
            raise ValueError(
                "requires_delivery_action conflicts with explicit delivery_action"
            )
        normalized["delivery_action"] = "create_review_request"
        notes.append(
            "legacy requires_delivery_action mapped to create_review_request"
        )
    if legacy_full:
        normalized["execution_preference"] = "controlled"
        notes.append("legacy full-workflow request mapped to controlled depth")

    validate_file(normalized, REQUEST_SCHEMA, "workflow request")

    routes = config["skill_routing"]["task_routes"]
    route_id = normalized["task_route"]
    if route_id not in routes:
        raise ValueError(f"unsupported task_route: {route_id}")
    route = routes[route_id]

    workflow = config["workflow"]
    known_flags = set(workflow["high_risk_flags"]) | set(workflow["standard_flags"])
    unknown_flags = sorted(set(normalized["risk_flags"]) - known_flags)
    if unknown_flags:
        raise ValueError("unsupported risk flags: " + ", ".join(unknown_flags))

    if route_id == "quick_fix":
        conflicting = sorted(
            set(normalized["risk_flags"])
            & {"unclear_scope", "cross_module", "multiple_concerns"}
        )
        if conflicting:
            raise ValueError(
                "quick_fix is not bounded because of: "
                + ", ".join(conflicting)
                + "; use debug or general_change"
            )
        if normalized["concerns"] > 1:
            raise ValueError("quick_fix must have one concern; use general_change")
        if normalized["estimated_files"] > workflow["focused_max_files"]:
            raise ValueError(
                "quick_fix exceeds the global bounded-file limit; use general_change"
            )

    delivery_action = normalized["delivery_action"]
    if delivery_action not in config["delivery_actions"]:
        raise ValueError(f"unsupported delivery_action: {delivery_action}")
    if (
        delivery_action != "none"
        and not route["source_editing"]
        and route_id not in {"review", "delivery"}
    ):
        raise ValueError("delivery action is incompatible with this read-only task route")
    if route_id == "delivery" and delivery_action == "none":
        raise ValueError("delivery route requires an explicit delivery_action")

    return normalized, notes


def _skill(config: dict[str, Any], token: str) -> str:
    routing = config["skill_routing"]
    for group in ("process_skills", "role_skills"):
        value = routing[group].get(token)
        if isinstance(value, str) and value.strip():
            return value.strip()
    raise ValueError(f"unknown routing token: {token}")


def _state_skill(config: dict[str, Any]) -> str:
    value = config["agents"]["agent-state-tools"].get("skill")
    if not isinstance(value, str) or not value.strip():
        raise ValueError("agent-state-tools.skill must be configured")
    return value.strip()


def _insert_before(tokens: list[str], token: str, anchors: tuple[str, ...]) -> None:
    if token in tokens:
        return
    for index, current in enumerate(tokens):
        if current in anchors:
            tokens.insert(index, token)
            return
    tokens.insert(0, token)


def _insert_review(tokens: list[str]) -> None:
    if "review" in tokens:
        return
    for anchor in ("batch_review", "verify", "delivery"):
        if anchor in tokens:
            tokens.insert(tokens.index(anchor), "review")
            return
    tokens.append("review")


def _insert_batch_review(tokens: list[str]) -> None:
    if "batch_review" in tokens:
        return
    for anchor in ("verify", "delivery"):
        if anchor in tokens:
            tokens.insert(tokens.index(anchor), "batch_review")
            return
    tokens.append("batch_review")


def _insert_verify(tokens: list[str]) -> None:
    if "verify" in tokens:
        return
    if "delivery" in tokens:
        tokens.insert(tokens.index("delivery"), "verify")
    else:
        tokens.append("verify")


def _normalize_final_gates(tokens: list[str]) -> list[str]:
    """Keep final gates deterministic: review, batch review, verify, delivery."""
    unique = list(dict.fromkeys(tokens))
    gates = [token for token in ("review", "batch_review", "verify", "delivery") if token in unique]
    return [token for token in unique if token not in set(gates)] + gates


def _resolve_state_mode(
    route: dict[str, Any],
    depth: str,
    policy: dict[str, Any],
    request: dict[str, Any],
    config: dict[str, Any],
) -> str:
    override = route["state_mode"]
    state_mode = override if override != "inherit" else config["runtime"][f"{depth}_state"]
    if policy["persist_state"] and depth != "focused":
        state_mode = "required"
    if "requires_persistent_state" in request["risk_flags"]:
        state_mode = "required"
    if request["delivery_action"] != "none" or request["task_route"] in {
        "recovery",
        "delivery",
    }:
        state_mode = "required"
    return state_mode


def _resolve_approval(
    request: dict[str, Any], config: dict[str, Any], route: dict[str, Any]
) -> tuple[dict[str, Any], dict[str, Any]]:
    workflow = config["workflow"]
    matrix = config["approval_matrix"]
    action = config["delivery_actions"][request["delivery_action"]]

    keys = {"normal_change"}
    reasons = ["normal bounded work follows the configured approval policy"]
    if route["source_editing"] or request["delivery_action"] != "none":
        for flag in sorted(request["risk_flags"]):
            approval_key = workflow["risk_approval_map"].get(flag)
            if approval_key:
                keys.add(approval_key)
                reasons.append(f"risk flag {flag} maps to approval key {approval_key}")
    if request["delivery_action"] != "none":
        keys.add(action["approval_key"])
        reasons.append(
            f"delivery action {request['delivery_action']} maps to approval key {action['approval_key']}"
        )

    ordered_keys = sorted(keys)
    required = any(matrix[key] == "user" for key in ordered_keys)
    approval = {
        "required": required,
        "kind": "user" if required else "automatic",
        "keys": ordered_keys,
        "reasons": reasons,
    }
    delivery = {
        "action": request["delivery_action"],
        "outcome": action["outcome"],
        "cleanup": action["cleanup"],
        "approval_key": action["approval_key"],
        "approval_required": required,
    }
    return approval, delivery


def _runtime_actions(
    state_mode: str, tokens: list[str], task_route: str, worktree_required: bool
) -> dict[str, list[str]]:
    if state_mode != "required" or task_route == "recovery":
        return {"before": [], "after": []}
    if task_route == "delivery":
        return {"before": ["init_runtime"], "after": ["validate_state"]}
    after: list[str] = []
    if "verify" in tokens:
        after.append("record_verification_evidence")
    after.append("mark_task_completed")
    if "verify" in tokens:
        after.append("verify_completion_claim")
    after.append("validate_state")
    before = ["init_runtime", "open_task"]
    if worktree_required:
        before.append("prepare_worktree")
    return {
        "before": before,
        "after": after,
    }


def _worktree_contract(depth: str, source_editing: bool) -> dict[str, Any]:
    required = depth == "controlled" and source_editing
    return {
        "enabled": required,
        "required": required,
        "mode": "required" if required else "disabled",
        "path_template": ".phongka/worktrees/{task_id}",
        "branch_template": "phongka/task/{task_id}",
        "prepare_approval_required": required,
        "delivery_approval_required": required,
        "cleanup_approval_required": required,
    }



def _subagent_plan(depth: str, tokens: list[str], config: dict[str, Any]) -> dict[str, Any]:
    policy = config["subagent_policy"]
    limits = policy["depths"][depth]
    dispatchable = set(policy["dispatchable_stages"])
    eligible = [token for token in tokens if token in dispatchable]

    model_parallel_safety: dict[str, bool] = {}
    for token in eligible:
        skill = _skill(config, token)
        matching = [
            record for record in config["agents"].values()
            if record.get("dispatch_kind") == "model" and record.get("skill") == skill
        ]
        model_parallel_safety[token] = bool(matching) and all(
            record.get("parallel_safe") is True for record in matching
        )

    return {
        "primary_count": 1,
        "max_active": limits["max_active"],
        "max_total": limits["max_total"],
        "max_parallel_writers": limits["max_parallel_writers"],
        "max_repair_rounds": limits["max_repair_rounds"],
        "fresh_context_per_dispatch": policy["fresh_context_per_dispatch"],
        "synthesized_fallback": policy["synthesized_fallback"],
        "eligible_roles": eligible,
        "parallel_safe_roles": [
            token for token in eligible if model_parallel_safety[token]
        ],
    }

def resolve_workflow(
    request: dict[str, Any], config: dict[str, Any] | None = None
) -> dict[str, Any]:
    config = config or load_config()
    request, legacy_notes = _normalized_request(request, config)
    profile = resolve_profile(request["profile"])
    policy = profile["workflow_policy"]
    workflow = config["workflow"]
    for depth in workflow["depth_order"]:
        central = workflow[f"{depth}_max_repair_cycles"]
        dispatch = config["subagent_policy"]["depths"][depth]["max_repair_rounds"]
        if central != dispatch:
            raise ValueError(f"repair limit sources diverge for {depth}: {central}!={dispatch}")
    routes = config["skill_routing"]["task_routes"]
    route = routes[request["task_route"]]
    depth_order = workflow["depth_order"]

    flags = set(request["risk_flags"])
    high = flags & set(workflow["high_risk_flags"])
    medium = flags & set(workflow["standard_flags"])
    approval, delivery = _resolve_approval(request, config, route)
    reasons: list[str] = [
        f"task route {request['task_route']}: {route['description']}",
        *legacy_notes,
    ]

    depth = _max_depth(depth_order, route["default_depth"], policy["minimum_depth"])
    if route["default_depth"] != "focused":
        reasons.append(f"route minimum depth is {route['default_depth']}")
    if policy["minimum_depth"] != "focused":
        reasons.append(
            f"profile {profile['profile_id']} requires at least {policy['minimum_depth']} depth"
        )

    preference = request["execution_preference"]
    if preference != "auto":
        previous = depth
        depth = _max_depth(depth_order, depth, preference)
        reasons.append(
            f"execution preference {preference}"
            + (
                " escalated the route"
                if depth != previous
                else " respected route/profile minimum"
            )
        )

    focused_file_limit = min(policy["focused_max_files"], workflow["focused_max_files"])
    focused_concern_limit = min(
        policy["focused_max_concerns"], workflow["focused_max_concerns"]
    )
    if high:
        depth = "controlled"
        reasons.append("high-risk flags: " + ", ".join(sorted(high)))
    else:
        if medium:
            depth = _max_depth(depth_order, depth, "standard")
            reasons.append("standard escalation flags: " + ", ".join(sorted(medium)))
        if request["estimated_files"] > workflow["standard_max_files"]:
            depth = "controlled"
            reasons.append(
                f"estimated files exceed standard limit ({request['estimated_files']}>{workflow['standard_max_files']})"
            )
        else:
            if request["estimated_files"] > focused_file_limit:
                depth = _max_depth(depth_order, depth, "standard")
                reasons.append(
                    f"estimated files exceed focused limit ({request['estimated_files']}>{focused_file_limit})"
                )
            if request["concerns"] > focused_concern_limit:
                depth = _max_depth(depth_order, depth, "standard")
                reasons.append(
                    f"concerns exceed focused limit ({request['concerns']}>{focused_concern_limit})"
                )

    if approval["required"]:
        depth = "controlled"
        reasons.append(
            "user approval is required for: " + ", ".join(approval["keys"])
        )

    tokens = list(route["sequences"][depth])
    if "unclear_scope" in flags and route["clarify_on_unclear"]:
        _insert_before(
            tokens,
            "brainstorm",
            ("explore", "plan", "implement", "configuration", "skill_authoring"),
        )
        reasons.append("unclear scope adds a focused clarification stage")

    independent_policy = policy["independent_review"]
    risk_based_review = independent_policy == "risk_based" and bool(medium | high)
    review_required = route["reviewable"] and (
        request["user_requested_review"]
        or independent_policy == "required"
        or risk_based_review
    )
    if review_required:
        if request["task_route"] == "plan":
            if "plan_review" not in tokens:
                tokens.append("plan_review")
        else:
            _insert_review(tokens)
        if request["user_requested_review"]:
            reasons.append("independent review requested")
        elif independent_policy == "required":
            reasons.append(f"profile {profile['profile_id']} requires independent review")
        else:
            reasons.append("risk-based profile review activated")

    batch_required = route["batch_reviewable"] and depth == "controlled" and (
        policy["batch_review"]
        or request["concerns"] > 1
        or "multiple_concerns" in flags
    )
    if batch_required:
        _insert_batch_review(tokens)
        reasons.append("controlled multi-concern work adds batch review")

    if request["delivery_action"] != "none":
        if "verify" not in tokens:
            _insert_verify(tokens)
            reasons.append("delivery requires current verification evidence")
        if "delivery" not in tokens:
            tokens.append("delivery")
        reasons.append(f"delivery action requested: {request['delivery_action']}")

    tokens = _normalize_final_gates(tokens)
    core = _skill(config, "core")
    companions = list(config["skill_routing"]["required_companion_skills"])
    state_skill = _state_skill(config)
    prefix = [core] + companions
    required = prefix + [_skill(config, token) for token in tokens]

    state_mode = _resolve_state_mode(route, depth, policy, request, config)
    optional: list[str] = []
    if state_mode == "required":
        required.insert(len(prefix), state_skill)
        optional.append(state_skill)
    elif state_mode == "optional":
        optional.append(state_skill)
    required = list(dict.fromkeys(required))
    optional = [skill for skill in dict.fromkeys(optional) if skill not in required]

    effective_quality = _max_quality(profile["quality_level"], DEPTH_TO_QUALITY[depth])
    effective_verification = _max_quality(
        policy["verification_level"], DEPTH_TO_QUALITY[depth]
    )
    worktree = _worktree_contract(depth, route["source_editing"])
    runtime_actions = _runtime_actions(
        state_mode, tokens, request["task_route"], worktree["required"]
    )
    evidence_requirements = {
        "verification": "verify" in tokens,
        "review": "review" in tokens,
        "batch_review": "batch_review" in tokens,
    }
    plan_gate = {
        "required": depth == "controlled" and "plan_review" in tokens,
        "schema_version": 5,
        "plan_bundle_hash": request.get("plan_bundle_hash"),
        "plan_review_hash": request.get("plan_review_hash"),
        "plan_task_ids": list(request.get("plan_task_ids", [])),
    }

    stages: list[dict[str, str]] = [
        {
            "id": "route",
            "owner": "primary",
            "output": "task route, execution depth, scope, acceptance, and approval contract",
        }
    ]
    task_route = request["task_route"]
    if state_mode == "required" and task_route != "recovery":
        stages.append(
            {
                "id": "state_init",
                "owner": state_skill,
                "output": "runtime initialized or rebound to the current workflow decision",
            }
        )

    approval_inserted = False
    state_finalized = False
    approval_anchors = {"implement", "configuration", "skill_authoring", "delivery"}
    for token in tokens:
        if (
            token == "delivery"
            and state_mode == "required"
            and task_route not in {"recovery", "delivery"}
            and not state_finalized
        ):
            stages.append(
                {
                    "id": "state_finalize",
                    "owner": state_skill,
                    "output": "task closure, current evidence, completion gate when required, and validated runtime state",
                }
            )
            state_finalized = True
        if approval["required"] and not approval_inserted and token in approval_anchors:
            stages.append(
                {
                    "id": "approval_gate",
                    "owner": "primary",
                    "output": "explicit user approval reference for the configured approval keys",
                }
            )
            approval_inserted = True
        stages.append(
            {
                "id": token,
                "owner": _skill(config, token),
                "output": STAGE_OUTPUTS.get(token, "bounded role result"),
            }
        )
    if approval["required"] and not approval_inserted:
        stages.append(
            {
                "id": "approval_gate",
                "owner": "primary",
                "output": "explicit user approval reference for the configured approval keys",
            }
        )
    if (
        state_mode == "required"
        and task_route not in {"recovery", "delivery"}
        and not state_finalized
    ):
        stages.append(
            {
                "id": "state_finalize",
                "owner": state_skill,
                "output": "task closure, current evidence, completion gate when required, and validated runtime state",
            }
        )
    stages.append(
        {
            "id": "report",
            "owner": "primary",
            "output": "outcome, evidence, risks, and next action",
        }
    )

    result: dict[str, Any] = {
        "schema_version": 8,
        "config_hash": sha256_json(config),
        "profile_id": profile["profile_id"],
        "profile_hash": profile["profile_hash"],
        "project_profile": profile["project_profile"],
        "quality_level": effective_quality,
        "verification_level": effective_verification,
        "task_route": request["task_route"],
        "execution_depth": depth,
        "allows_source_editing": route["source_editing"],
        "state_mode": state_mode,
        "request_contract": {
            "execution_preference": request["execution_preference"],
            "estimated_files": request["estimated_files"],
            "concerns": request["concerns"],
            "risk_flags": sorted(request["risk_flags"]),
            "user_requested_review": request["user_requested_review"],
            "delivery_action": request["delivery_action"],
            "plan_bundle_hash": request.get("plan_bundle_hash"),
            "plan_review_hash": request.get("plan_review_hash"),
            "plan_task_ids": list(request.get("plan_task_ids", [])),
        },
        "approval": approval,
        "delivery": delivery,
        "evidence_requirements": evidence_requirements,
        "plan_gate": plan_gate,
        "runtime_actions": runtime_actions,
        "subagent_plan": _subagent_plan(depth, tokens, config),
        "context_budget": {
            "max_files": config["context_budget"][f"{depth}_max_files"],
            "max_bytes": config["context_budget"]["max_bytes"],
            "allow_unbounded_scan": config["context_budget"]["allow_unbounded_scan"],
        },
        "execution_contract": {
            "dispatch": {
                "max_active": config["subagent_policy"]["depths"][depth]["max_active"],
                "max_total": config["subagent_policy"]["depths"][depth]["max_total"],
                "max_parallel_writers": config["subagent_policy"]["depths"][depth]["max_parallel_writers"],
                "fresh_context_per_dispatch": config["subagent_policy"]["fresh_context_per_dispatch"],
                "synthesized_fallback": config["subagent_policy"]["synthesized_fallback"],
            },
            "repair": {
                "max_repair_rounds": workflow[f"{depth}_max_repair_cycles"],
                "re_review_required": "review" in tokens or "batch_review" in tokens,
            },
            "receipt": {
                "required_fields": [
                    "workflow_decision_hash",
                    "task_id",
                    "stage",
                    "role",
                    "status",
                    "attempt",
                    "max_attempts",
                    "repair_rounds",
                    "max_repair_rounds",
                    "outcome",
                    "evidence",
                ],
                "fallback_values": ["NONE", "SYNTHESIZED FALLBACK", "BLOCKED"],
            },
        },
        "worktree": worktree,
        "required_skills": required,
        "optional_skills": optional,
        "stages": stages,
        "limits": {
            "max_repair_cycles": workflow[f"{depth}_max_repair_cycles"],
            "max_context_files": config["context_budget"][f"{depth}_max_files"],
            "max_context_bytes": config["context_budget"]["max_bytes"],
            "focused_file_limit": focused_file_limit,
            "focused_concern_limit": focused_concern_limit,
        },
        "reasons": reasons,
    }
    result["decision_hash"] = sha256_json(result)
    validate_file(result, DECISION_SCHEMA, "workflow decision")
    return result


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--input")
    parser.add_argument("--profile")
    parser.add_argument("--task-route")
    parser.add_argument(
        "--execution",
        choices=["auto", "focused", "standard", "controlled"],
        default="auto",
    )
    parser.add_argument("--change-type", help="legacy v2.1 compatibility")
    parser.add_argument("--estimated-files", type=int, default=1)
    parser.add_argument("--concerns", type=int, default=1)
    parser.add_argument("--risk", action="append", default=[])
    parser.add_argument("--review", action="store_true")
    parser.add_argument("--full", action="store_true", help="legacy alias for controlled depth")
    parser.add_argument(
        "--delivery-action",
        choices=[
            "none",
            "keep_local",
            "merge_local",
            "push_branch",
            "create_review_request",
            "production_action",
            "destructive_cleanup",
        ],
        default="none",
    )
    parser.add_argument(
        "--delivery",
        action="store_true",
        help="legacy alias for --delivery-action create_review_request",
    )
    parser.add_argument("--config")
    parser.add_argument("--output")
    args = parser.parse_args()
    try:
        if args.input:
            request = json.loads(Path(args.input).read_text(encoding="utf-8"))
        else:
            request = {
                "execution_preference": args.execution,
                "estimated_files": args.estimated_files,
                "concerns": args.concerns,
                "risk_flags": args.risk,
                "user_requested_review": args.review,
                "delivery_action": args.delivery_action,
            }
            if args.profile:
                request["profile"] = args.profile
            if args.delivery:
                if args.delivery_action != "none":
                    raise ValueError("--delivery conflicts with --delivery-action")
                request["requires_delivery_action"] = True
                request.pop("delivery_action")
            if args.task_route:
                request["task_route"] = args.task_route
            if args.change_type:
                request["change_type"] = args.change_type
            if args.full:
                request["explicit_full_workflow"] = True
        result = resolve_workflow(request, load_config(args.config))
        if args.output:
            write_json_atomic(args.output, result)
    except (OSError, ValueError, TypeError, KeyError, json.JSONDecodeError) as exc:
        print(f"WORKFLOW_REJECTED: {exc}", file=sys.stderr)
        return 1
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
