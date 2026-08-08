"""Run deterministic workflow-routing exams."""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--skills-root", required=True)
    args = parser.parse_args()
    root = Path(args.skills_root).expanduser().resolve()
    sys.path.insert(0, str(root / "agentic-state-tools/scripts"))
    sys.path.insert(0, str(root / "agentic-configuration/scripts"))
    from load_config import load_config
    from resolve_workflow import resolve_workflow

    cases = json.loads((root / "agentic-engineering-core/exams/workflow-routing.json").read_text(encoding="utf-8"))
    failures = []
    config = load_config()
    for case in cases:
        try:
            result = resolve_workflow(case["request"], config)
            expect = case["expect"]
            for key, value in expect.items():
                if key == "max_active":
                    actual = result["subagent_plan"][key]
                elif key == "max_total":
                    actual = result["subagent_plan"][key]
                elif key == "approval_required":
                    actual = result["approval"]["required"]
                elif key == "eligible_contains":
                    missing = [x for x in value if x not in result["subagent_plan"]["eligible_roles"]]
                    if missing:
                        failures.append(f"{case['name']}: missing eligible roles {missing}")
                    continue
                elif key == "required_contains":
                    missing = [x for x in value if x not in result["required_skills"]]
                    if missing:
                        failures.append(f"{case['name']}: missing required skills {missing}")
                    continue
                elif key == "stage_order":
                    ids = [stage["id"] for stage in result["stages"]]
                    positions = [ids.index(item) for item in value if item in ids]
                    missing = [item for item in value if item not in ids]
                    if missing or positions != sorted(positions):
                        failures.append(f"{case['name']}: invalid stage order {value}; actual={ids}")
                    continue
                elif key == "forbidden_stages":
                    ids = [stage["id"] for stage in result["stages"]]
                    found = [item for item in value if item in ids]
                    if found:
                        failures.append(f"{case['name']}: forbidden stages present {found}")
                    continue
                elif key == "parallel_safe_contains":
                    missing = [x for x in value if x not in result["subagent_plan"]["parallel_safe_roles"]]
                    if missing:
                        failures.append(f"{case['name']}: missing parallel-safe roles {missing}")
                    continue
                elif key == "parallel_safe_excludes":
                    found = [x for x in value if x in result["subagent_plan"]["parallel_safe_roles"]]
                    if found:
                        failures.append(f"{case['name']}: unexpectedly parallel-safe roles {found}")
                    continue
                else:
                    actual = result.get(key)
                if actual != value:
                    failures.append(f"{case['name']}: {key} expected {value!r}, got {actual!r}")
        except Exception as exc:
            failures.append(f"{case['name']}: {type(exc).__name__}: {exc}")
    # Exhaustive deterministic gate-order invariant across every route/profile/depth preference.
    profiles = [path.stem for path in (root / "agentic-state-tools/profiles").glob("*.json")]
    routes = config["skill_routing"]["task_routes"]
    matrix_cases = 0
    for profile in profiles:
        for route_id, route in routes.items():
            for preference in ("focused", "standard", "controlled"):
                request = {
                    "profile": profile,
                    "task_route": route_id,
                    "execution_preference": preference,
                    "estimated_files": 1 if route["source_editing"] else 0,
                    "concerns": 1,
                }
                if route_id == "delivery":
                    request["delivery_action"] = "create_review_request"
                try:
                    result = resolve_workflow(request, config)
                except ValueError:
                    continue
                matrix_cases += 1
                ids = [stage["id"] for stage in result["stages"]]
                if "review" in ids and "verify" in ids and ids.index("review") > ids.index("verify"):
                    failures.append(f"matrix {profile}/{route_id}/{preference}: review after verify")
                if "batch_review" in ids and "verify" in ids and ids.index("batch_review") > ids.index("verify"):
                    failures.append(f"matrix {profile}/{route_id}/{preference}: batch review after verify")
                if "review" in ids and "batch_review" in ids and ids.index("review") > ids.index("batch_review"):
                    failures.append(f"matrix {profile}/{route_id}/{preference}: batch review before task review")
                if "delivery" in ids and "verify" in ids and ids.index("verify") > ids.index("delivery"):
                    failures.append(f"matrix {profile}/{route_id}/{preference}: delivery before verify")
                if "state_finalize" in ids and "delivery" in ids and ids.index("state_finalize") > ids.index("delivery"):
                    failures.append(f"matrix {profile}/{route_id}/{preference}: state finalization after delivery")
                if route_id == "recovery":
                    if "state_init" in ids or "state_finalize" in ids:
                        failures.append(f"matrix {profile}/{route_id}/{preference}: recovery rebinding/finalization stage present")
                    if result["runtime_actions"] != {"before": [], "after": []}:
                        failures.append(f"matrix {profile}/{route_id}/{preference}: recovery runtime actions are not empty")
                if route_id == "delivery":
                    if "state_finalize" in ids or "open_task" in result["runtime_actions"]["before"]:
                        failures.append(f"matrix {profile}/{route_id}/{preference}: standalone delivery opens/finalizes a task")
                if result["state_mode"] == "optional" and result["runtime_actions"] != {"before": [], "after": []}:
                    failures.append(f"matrix {profile}/{route_id}/{preference}: optional state has implicit runtime actions")
                if result["subagent_plan"]["max_parallel_writers"] != 1:
                    failures.append(f"matrix {profile}/{route_id}/{preference}: max_parallel_writers must be 1")
                writer_roles = {"implement", "skill_authoring"}
                unsafe = sorted(writer_roles & set(result["subagent_plan"]["parallel_safe_roles"]))
                if unsafe:
                    failures.append(f"matrix {profile}/{route_id}/{preference}: writer roles marked parallel-safe {unsafe}")
                if "context" in ids:
                    failures.append(f"matrix {profile}/{route_id}/{preference}: retired context stage present")

    if failures:
        print(json.dumps({"status":"FAILED","failures":failures}, indent=2))
        return 1
    print(json.dumps({"status":"PASSED","cases":len(cases),"matrix_cases":matrix_cases}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
