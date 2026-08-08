"""Run route-level and end-to-end smoke tests against the bundled workflow runtime."""
from __future__ import annotations

import argparse
import json
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import Any

RUBRIC_SOURCE = (
    Path(__file__).resolve().parents[2]
    / "agentic-independent-reviewer"
    / "references"
    / "review-rubrics.json"
)


def _load_canonical_rubrics() -> dict[str, dict[str, Any]]:
    source = json.loads(RUBRIC_SOURCE.read_text(encoding="utf-8"))
    rubrics = source["rubrics"]
    if set(rubrics) != {"plan", "task", "integration"}:
        raise ValueError("canonical review rubrics must contain exactly plan, task, and integration")
    return rubrics


REVIEW_RUBRICS = _load_canonical_rubrics()

ROUTES = (
    "quick_fix",
    "debug",
    "feature",
    "refactor",
    "research",
    "brainstorm",
    "plan",
    "review",
    "documentation",
    "configuration",
    "skill_authoring",
    "recovery",
    "delivery",
    "general_change",
)


def _run(
    command: list[str], *, expect: int = 0, cwd: Path | None = None
) -> subprocess.CompletedProcess[str]:
    result = subprocess.run(
        command,
        text=True,
        capture_output=True,
        check=False,
        cwd=str(cwd) if cwd else None,
    )
    if result.returncode != expect:
        raise AssertionError(
            f"command returned {result.returncode}, expected {expect}: {' '.join(command)}\n"
            f"stdout:\n{result.stdout}\nstderr:\n{result.stderr}"
        )
    return result


def _write(path: Path, value: Any) -> Path:
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return path


def _json_stdout(result: subprocess.CompletedProcess[str]) -> dict[str, Any]:
    value = json.loads(result.stdout)
    if not isinstance(value, dict):
        raise AssertionError("command did not return a JSON object")
    return value


def _load_config(skills_root: Path) -> dict[str, Any]:
    config_path = skills_root / "agentic-configuration" / "config" / "agentic-config.json"
    return json.loads(config_path.read_text(encoding="utf-8"))


def _assert_companion_invariants(
    decision: dict[str, Any], config: dict[str, Any]
) -> None:
    routing = config["skill_routing"]
    core = routing["process_skills"]["core"]
    companions = routing["required_companion_skills"]
    prefix = [core, *companions]
    required = decision["required_skills"]
    route = decision["task_route"]
    if required[: len(prefix)] != prefix:
        raise AssertionError(f"{route}: required skill prefix is invalid: {required}")

    state_skill = config["agents"]["agent-state-tools"]["skill"]
    if decision["state_mode"] == "required":
        if state_skill not in required or required[len(prefix)] != state_skill:
            raise AssertionError(f"{route}: required state skill is not after companions: {required}")
    elif state_skill in required:
        raise AssertionError(f"{route}: stateless decision includes state skill: {required}")

    stage_ids = {stage["id"] for stage in decision["stages"]}
    stage_owners = {stage["owner"] for stage in decision["stages"]}
    if stage_ids & set(companions) or stage_owners & set(companions):
        raise AssertionError(f"{route}: companion was promoted to a stage: {decision['stages']}")
    if decision["stages"][0] != {
        "id": "route",
        "owner": "primary",
        "output": "task route, execution depth, scope, acceptance, and approval contract",
    }:
        raise AssertionError(f"{route}: route stage is not Primary-owned")
    if decision["stages"][-1]["id"] != "report" or decision["stages"][-1]["owner"] != "primary":
        raise AssertionError(f"{route}: report stage is not Primary-owned")


def _init_git_repo(project: Path) -> None:
    _run(["git", "init"], cwd=project)
    _run(["git", "config", "user.email", "smoke@example.invalid"], cwd=project)
    _run(["git", "config", "user.name", "Workflow Smoke"], cwd=project)
    _run(["git", "add", "."], cwd=project)
    _run(["git", "commit", "-m", "initial"], cwd=project)


def _active_workspace_path(project: Path, relative: str) -> Path:
    state = json.loads((project / ".phongka" / "state.json").read_text(encoding="utf-8"))
    identity = state.get("worktree_identity")
    root = project / identity["path"] if identity else project
    return root / relative


def _resolve(py: str, scripts: Path, output: Path, **request: Any) -> dict[str, Any]:
    payload = {
        "profile": "personal",
        "task_route": request.pop("task_route"),
        "execution_preference": request.pop("execution_preference", "auto"),
        "estimated_files": request.pop("estimated_files", 1),
        "concerns": request.pop("concerns", 1),
        "risk_flags": request.pop("risk_flags", []),
        "user_requested_review": request.pop("user_requested_review", False),
        "delivery_action": request.pop("delivery_action", "none"),
    }
    if request:
        raise AssertionError(f"unknown request keys: {sorted(request)}")
    request_path = output.with_suffix(".request.json")
    _write(request_path, payload)
    result = _run(
        [py, str(scripts / "resolve_workflow.py"), "--input", str(request_path), "--output", str(output)]
    )
    return _json_stdout(result)


def _workspace(py: str, scripts: Path, project: Path, relative: str, output: Path) -> dict[str, Any]:
    result = _run(
        [
            py,
            str(scripts / "capture_workspace.py"),
            "--project-root",
            str(project),
            "--path",
            relative,
        ]
    )
    value = _json_stdout(result)
    _write(output, value)
    return value


def _task_payload(status: str, approval_reference: str | None = None) -> dict[str, Any]:
    payload = {
        "task_id": "TASK-1",
        "status": status,
        "summary": "Implement one bounded behavior",
        "scope": ["src/module.txt"],
        "risk_flags": [],
    }
    if approval_reference:
        payload["approval_reference"] = approval_reference
    return payload


def _init_and_open(py: str, scripts: Path, project: Path, decision_path: Path) -> None:
    decision = json.loads(decision_path.read_text(encoding="utf-8"))
    approval = "workflow-smoke-approval" if decision["worktree"]["required"] else None
    if decision["worktree"]["required"]:
        _init_git_repo(project)
    init_command = [py, str(scripts / "init_runtime.py"), "--project-root", str(project), "--decision", str(decision_path)]
    if decision.get("plan_gate", {}).get("required"):
        plan_bundle = {
            "schema_version": 5,
            "review_rubric_id": "plan",
            "review_rubric_version": 1,
            "goal": "workflow smoke plan",
            "scope": ["src/module.txt"],
            "tasks": [{
                "id": "T1",
                "plan_task_id": "T1",
                "review_rubric_id": "task",
                "review_rubric_version": 1,
                "objective": "smoke",
                "files": ["src/module.txt"],
                "steps": ["verify"],
                "dependencies": [],
                "acceptance": ["A1", "A2"],
                "verification": ["smoke"],
                "rollback": "restore",
            }],
            "acceptance": [{"id": "A1", "description": "expected result"}, {"id": "A2", "description": "bounded file"}],
            "acceptance_ids": ["A1", "A2"],
            "verification": ["smoke"],
            "plan_task_ids": ["T1"],
        }
        plan_input = _write(project / "plan.json", plan_bundle)
        manifest_path = project / "plan-manifest.json"
        _run(
            [
                py,
                str(scripts / "create_plan_manifest.py"),
                "--input",
                str(plan_input),
                "--output",
                str(manifest_path),
                "--workflow-decision-hash",
                decision["decision_hash"],
            ]
        )
        plan_rubric = REVIEW_RUBRICS["plan"]
        review_input = _write(
            project / "plan-review-input.json",
            {
                "review_mode": "plan",
                "review_rubric_id": plan_rubric["id"],
                "review_rubric_version": plan_rubric["version"],
                "outcome": "PASS",
                "workflow_decision_hash": decision["decision_hash"],
                "criteria": _criterion_results("plan"),
            },
        )
        review_path = project / "plan-review.json"
        _run([py, str(scripts / "create_plan_review.py"), "--input", str(review_input), "--manifest", str(manifest_path), "--output", str(review_path)])
        if decision["worktree"]["required"]:
            _run(["git", "add", "plan.json", "plan-manifest.json", "plan-review-input.json", "plan-review.json"], cwd=project)
            _run(["git", "commit", "-m", "approved plan"], cwd=project)
        init_command.extend(["--plan-manifest", str(manifest_path), "--plan-review", str(review_path)])
    _run(init_command)
    state = json.loads((project / ".phongka" / "state.json").read_text(encoding="utf-8"))
    if state.get("required_skills") != decision["required_skills"] or state.get("stages") != decision["stages"]:
        raise AssertionError("runtime state did not retain the selected skills and stages")
    settings = json.loads(
        _run(
            [
                py,
                str(scripts / "load_runtime_settings.py"),
                "--project-root",
                str(project),
            ]
        ).stdout
    )
    wait = settings.get("subagent_wait", {})
    if wait.get("check_interval_seconds", 0) >= wait.get("timeout_seconds", 0):
        raise AssertionError("runtime settings contain an invalid subagent wait policy")
    task_path = project / ".phongka" / "task-input.json"
    task_payload = _task_payload("IN_PROGRESS", approval)
    if decision.get("plan_gate", {}).get("required"):
        task_payload["plan_task_id"] = "T1"
    _write(task_path, task_payload)
    _run([py, str(scripts / "update_task_state.py"), "--project-root", str(project), "--input", str(task_path)])
    if decision["worktree"]["required"]:
        _run(
            [
                py,
                str(scripts / "prepare_worktree.py"),
                "--project-root",
                str(project),
                "--approval-reference",
                approval,
                "--decision",
                str(decision_path),
            ]
        )


def _criterion_results(mode: str) -> list[dict[str, str]]:
    rubric = REVIEW_RUBRICS[mode]
    return [
        {
            "id": criterion["id"],
            "status": "PASS",
            "evidence": f"Workflow smoke evidence for {criterion['id']}",
        }
        for criterion in rubric["criteria"]
    ]


def _review_payload(workspace: dict[str, Any], *, findings: list[dict[str, str]] | None = None) -> dict[str, Any]:
    rubric = REVIEW_RUBRICS["task"]
    return {
        "schema_version": 5,
        "task_id": "TASK-1",
        "review_mode": "task",
        "review_rubric_id": rubric["id"],
        "review_rubric_version": rubric["version"],
        "criteria": _criterion_results("task"),
        "outcome": "PASS",
        "summary": "Independent review passed",
        "findings": findings or [],
        "workspace": workspace,
        "workspace_summary": "Reviewed the complete bounded workspace",
    }


def _batch_payload(workspace: dict[str, Any], *, outcome: str = "PASS", findings: list[dict[str, str]] | None = None) -> dict[str, Any]:
    rubric = REVIEW_RUBRICS["integration"]
    return {
        "schema_version": 3,
        "task_ids": ["TASK-1"],
        "review_mode": "integration",
        "review_rubric_id": rubric["id"],
        "review_rubric_version": rubric["version"],
        "criteria": _criterion_results("integration"),
        "outcome": outcome,
        "summary": "Integration review passed",
        "findings": findings or [],
        "workspace": workspace,
        "workspace_summary": "Reviewed integrated workspace before final verification",
    }


def _verification_payload(workspace: dict[str, Any]) -> dict[str, Any]:
    return {
        "schema_version": 3,
        "task_id": "TASK-1",
        "status": "PASS",
        "checks": [
            {"name": "A1", "status": "PASS", "evidence": "observed expected result"},
            {"name": "A2", "status": "PASS", "evidence": "reviewed bounded file"},
        ],
        "workspace": workspace,
        "workspace_summary": "Workspace after final material edit",
    }


def _claim_payload() -> dict[str, Any]:
    return {
        "schema_version": 3,
        "task_id": "TASK-1",
        "work_revision": 1,
        "claim": "Requested behavior is complete",
        "acceptance": [
            {"id": "A1", "status": "PASS", "evidence": "Observed expected result"},
            {"id": "A2", "status": "PASS", "evidence": "Only bounded file changed"},
        ],
        "verification_status": "PASS",
    }


def _claim_payload_for_project(project: Path) -> dict[str, Any]:
    value = _claim_payload()
    state_path = project / ".phongka" / "state.json"
    if state_path.is_file():
        binding = json.loads(state_path.read_text(encoding="utf-8")).get("plan_binding", {})
        if isinstance(binding, dict) and binding.get("bound"):
            value.update(
                {
                    "plan_task_id": "T1",
                    "plan_bundle_hash": binding["plan_bundle_hash"],
                    "plan_review_hash": binding["plan_review_hash"],
                    "acceptance_ids": list(binding["acceptance_ids"]),
                }
            )
    return value


def _delivery_payload() -> dict[str, Any]:
    return {
        "schema_version": 4,
        "task_ids": ["TASK-1"],
        "action": "keep_local",
        "outcome": "KEEP_LOCAL",
        "summary": "Keep the verified result locally",
        "approval_reference": "workflow-smoke-approval",
        "cleanup": "KEEP",
    }


def _write_and_run(py: str, script: Path, project: Path, name: str, payload: dict[str, Any], *, expect: int = 0) -> subprocess.CompletedProcess[str]:
    path = project / name
    _write(path, payload)
    return _run([py, str(script), "--project-root", str(project), "--input", str(path)], expect=expect)


def _assert_route_invariants(decision: dict[str, Any]) -> None:
    ids = [stage["id"] for stage in decision["stages"]]
    route = decision["task_route"]
    if ids[0] != "route" or ids[-1] != "report":
        raise AssertionError(f"{route}: route/report boundary is invalid: {ids}")
    if "review" in ids and "verify" in ids and ids.index("review") > ids.index("verify"):
        raise AssertionError(f"{route}: review occurs after verify")
    if "batch_review" in ids and "verify" in ids and ids.index("batch_review") > ids.index("verify"):
        raise AssertionError(f"{route}: batch review occurs after verify")
    if "delivery" in ids and "verify" in ids and ids.index("verify") > ids.index("delivery"):
        raise AssertionError(f"{route}: delivery occurs before verify")
    if route == "recovery":
        if "state_init" in ids or "state_finalize" in ids or decision["runtime_actions"] != {"before": [], "after": []}:
            raise AssertionError("recovery must inspect existing runtime without rebinding or opening a task")
    if route == "delivery":
        if "state_finalize" in ids or "open_task" in decision["runtime_actions"]["before"]:
            raise AssertionError("standalone delivery must not create or finalize a new task")
    if decision["state_mode"] == "optional" and decision["runtime_actions"] != {"before": [], "after": []}:
        raise AssertionError(f"{route}: optional state must not emit implicit runtime actions")
    if decision["subagent_plan"]["max_parallel_writers"] != 1:
        raise AssertionError(f"{route}: single-active-task runtime must allow one writer")
    if decision["limits"]["max_context_bytes"] != decision["context_budget"]["max_bytes"]:
        raise AssertionError(f"{route}: context byte limit is not bound to the decision budget")
    dispatch = decision["execution_contract"]["dispatch"]
    for field in (
        "max_active",
        "max_total",
        "max_parallel_writers",
        "fresh_context_per_dispatch",
        "synthesized_fallback",
    ):
        if field not in dispatch:
            raise AssertionError(f"{route}: dispatch contract omits {field}")
    if decision["execution_contract"]["repair"].get("max_repair_rounds") != decision["limits"]["max_repair_cycles"]:
        raise AssertionError(f"{route}: repair contract is not bound to the decision limit")
    if decision["execution_contract"]["receipt"]["fallback_values"] != [
        "NONE",
        "SYNTHESIZED FALLBACK",
        "BLOCKED",
    ]:
        raise AssertionError(f"{route}: receipt fallback values are not explicit")
    expected_worktree = (
        decision["execution_depth"] == "controlled"
        and decision["allows_source_editing"]
        and decision["task_route"] not in {
            "review",
            "recovery",
            "delivery",
        }
    )
    if decision["worktree"]["required"] != expected_worktree:
        raise AssertionError(f"{route}: worktree requirement is not bounded to controlled source editing")
    if expected_worktree and "prepare_worktree" not in decision["runtime_actions"]["before"]:
        raise AssertionError(f"{route}: controlled source editing omits worktree preparation")
    if any(role in decision["subagent_plan"]["parallel_safe_roles"] for role in ("implement", "skill_authoring")):
        raise AssertionError(f"{route}: writer role is incorrectly marked parallel-safe")


def _route_smoke(
    py: str, scripts: Path, root: Path, config: dict[str, Any]
) -> int:
    count = 0
    for route in ROUTES:
        for depth in ("focused", "standard", "controlled"):
            output = root / f"{route}-{depth}.decision.json"
            kwargs: dict[str, Any] = {
                "task_route": route,
                "execution_preference": depth,
                "estimated_files": 0 if route in {"research", "brainstorm", "plan", "review", "recovery", "delivery"} else 1,
            }
            if route == "delivery":
                kwargs["delivery_action"] = "keep_local"
            decision = _resolve(py, scripts, output, **kwargs)
            _assert_route_invariants(decision)
            _assert_companion_invariants(decision, config)
            count += 1
    return count


def _stateful_delivery_smoke(py: str, scripts: Path, root: Path) -> int:
    project = root / "stateful-source-delivery"
    (project / "src").mkdir(parents=True)
    target = project / "src/module.txt"
    target.write_text("version one\n", encoding="utf-8")
    decision_path = project / "decision.json"
    decision = _resolve(
        py,
        scripts,
        decision_path,
        task_route="feature",
        execution_preference="controlled",
        estimated_files=1,
        concerns=2,
        delivery_action="keep_local",
    )
    ids = [stage["id"] for stage in decision["stages"]]
    expected = ["review", "batch_review", "verify", "state_finalize", "delivery"]
    positions = [ids.index(item) for item in expected]
    if positions != sorted(positions):
        raise AssertionError(f"source delivery gate order is invalid: {ids}")
    _init_and_open(py, scripts, project, decision_path)

    workspace_v1 = _workspace(py, scripts, project, "src/module.txt", project / "workspace-v1.json")
    high = {
        "severity": "HIGH",
        "summary": "Blocking issue",
        "location": "src/module.txt:1",
        "evidence": "test evidence",
        "impact": "wrong result",
        "correction": "fix the line",
    }
    _write_and_run(
        py,
        scripts / "create_review.py",
        project,
        "invalid-review.json",
        _review_payload(workspace_v1, findings=[high]),
        expect=1,
    )
    _write_and_run(
        py,
        scripts / "create_batch_review.py",
        project,
        "invalid-batch.json",
        _batch_payload(workspace_v1, outcome="REPAIR_REQUIRED", findings=[]),
        expect=1,
    )
    _write_and_run(py, scripts / "create_review.py", project, "review-v1.json", _review_payload(workspace_v1))
    _write_and_run(py, scripts / "create_batch_review.py", project, "batch-v1.json", _batch_payload(workspace_v1))

    _active_workspace_path(project, "src/module.txt").write_text("version two\n", encoding="utf-8")
    workspace_v2 = _workspace(py, scripts, project, "src/module.txt", project / "workspace-v2.json")
    _write_and_run(py, scripts / "record_verification_evidence.py", project, "verification.json", _verification_payload(workspace_v2))
    _write(project / "task-complete.json", _task_payload("COMPLETED"))
    _run([py, str(scripts / "update_task_state.py"), "--project-root", str(project), "--input", str(project / "task-complete.json")])
    _write_and_run(py, scripts / "verify_completion_claim.py", project, "claim.json", _claim_payload_for_project(project))
    _run([py, str(scripts / "validate_state.py"), "--project-root", str(project)])
    _run(
        [
            py,
            str(scripts / "cleanup_worktree.py"),
            "--project-root",
            str(project),
            "--task-id",
            "TASK-1",
            "--approval-reference",
            "workflow-smoke-approval",
            "--outcome",
            "KEPT",
            "--summary",
            "worktree retained for smoke delivery",
        ]
    )
    _write_and_run(py, scripts / "finalize_delivery.py", project, "delivery-stale.json", _delivery_payload(), expect=1)

    _write_and_run(py, scripts / "create_review.py", project, "review-v2.json", _review_payload(workspace_v2))
    _write_and_run(py, scripts / "create_batch_review.py", project, "batch-v2.json", _batch_payload(workspace_v2))
    _write_and_run(py, scripts / "finalize_delivery.py", project, "delivery.json", _delivery_payload())
    _run([py, str(scripts / "project_dashboard.py"), "--project-root", str(project)])
    _run(
        [
            py,
            str(scripts / "render_checklist.py"),
            "--project-root",
            str(project),
            "--task-id",
            "TASK-1",
            "--current-stage",
            "verify",
            "--current-skill",
            "agentic-verification-before-completion",
        ]
    )
    checklist = project / ".phongka" / "checklist" / "task-checklist-TASK-1.md"
    if not checklist.is_file():
        raise AssertionError("task-specific checklist was not rendered")
    if (project / ".phongka" / "checklist" / "README.md").exists():
        raise AssertionError("generic checklist README must not be generated")
    checklist_text = checklist.read_text(encoding="utf-8")
    if "Current skill: `agentic-verification-before-completion`" not in checklist_text:
        raise AssertionError("checklist did not record the current skill")
    stage_ids = [stage["id"] for stage in decision["stages"]]
    current_index = stage_ids.index("verify")
    for index, stage_id in enumerate(stage_ids):
        marker = next(
            (line for line in checklist_text.splitlines() if f"`{stage_id}` - " in line),
            None,
        )
        expected = "[x]" if index <= current_index else "[ ]"
        if marker is None or not marker.startswith(f"- {expected}"):
            raise AssertionError(f"stage {stage_id} did not render reached progress")
    if "reached, not completion" not in checklist_text:
        raise AssertionError("checklist did not explain reached-stage checkbox semantics")
    if (project / ".phongka" / "checklist.md").exists():
        raise AssertionError("legacy checklist.md must not be generated")
    return 1


def _recovery_smoke(py: str, scripts: Path, root: Path) -> int:
    project = root / "recovery"
    (project / "src").mkdir(parents=True)
    (project / "src/module.txt").write_text("unfinished\n", encoding="utf-8")
    decision_path = project / "decision.json"
    _resolve(
        py,
        scripts,
        decision_path,
        task_route="feature",
        execution_preference="controlled",
        estimated_files=1,
    )
    _init_and_open(py, scripts, project, decision_path)
    recovery_path = project / "recovery-decision.json"
    recovery = _resolve(py, scripts, recovery_path, task_route="recovery", estimated_files=0)
    _assert_route_invariants(recovery)
    result = _json_stdout(_run([py, str(scripts / "inspect_recovery.py"), "--project-root", str(project)]))
    if result["status"] != "RECOVERY_REQUIRED" or result["next_action"] != "INSPECT_WORKSPACE":
        raise AssertionError(f"unexpected recovery result: {result}")
    return 1


def _standalone_delivery_smoke(py: str, scripts: Path, root: Path) -> int:
    project = root / "standalone-delivery"
    (project / "src").mkdir(parents=True)
    target = project / "src/module.txt"
    target.write_text("complete\n", encoding="utf-8")
    source_decision_path = project / "source-decision.json"
    _resolve(
        py,
        scripts,
        source_decision_path,
        task_route="feature",
        execution_preference="controlled",
        estimated_files=1,
    )
    _init_and_open(py, scripts, project, source_decision_path)
    workspace = _workspace(py, scripts, project, "src/module.txt", project / "workspace.json")
    _write_and_run(py, scripts / "create_review.py", project, "source-review.json", _review_payload(workspace))
    _write_and_run(py, scripts / "record_verification_evidence.py", project, "source-verification.json", _verification_payload(workspace))
    _write(project / "source-complete.json", _task_payload("COMPLETED"))
    _run([py, str(scripts / "update_task_state.py"), "--project-root", str(project), "--input", str(project / "source-complete.json")])
    _write_and_run(py, scripts / "verify_completion_claim.py", project, "source-claim.json", _claim_payload_for_project(project))

    delivery_decision_path = project / "delivery-decision-workflow.json"
    delivery_decision = _resolve(
        py,
        scripts,
        delivery_decision_path,
        task_route="delivery",
        estimated_files=0,
        delivery_action="keep_local",
    )
    _assert_route_invariants(delivery_decision)
    _run([py, str(scripts / "init_runtime.py"), "--project-root", str(project), "--decision", str(delivery_decision_path)])
    # Standalone delivery reviews and verifies selected prior tasks without opening a new task.
    _write_and_run(py, scripts / "create_review.py", project, "delivery-review.json", _review_payload(workspace))
    _write_and_run(py, scripts / "record_verification_evidence.py", project, "delivery-verification.json", _verification_payload(workspace))
    _write_and_run(py, scripts / "verify_completion_claim.py", project, "delivery-claim.json", _claim_payload_for_project(project))
    _run([py, str(scripts / "validate_state.py"), "--project-root", str(project)])
    _run(
        [
            py,
            str(scripts / "cleanup_worktree.py"),
            "--project-root",
            str(project),
            "--task-id",
            "TASK-1",
            "--approval-reference",
            "workflow-smoke-approval",
            "--outcome",
            "KEPT",
            "--summary",
            "worktree retained for standalone delivery",
        ]
    )
    _write_and_run(py, scripts / "finalize_delivery.py", project, "standalone-delivery.json", _delivery_payload())
    return 1


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--skills-root", required=True)
    args = parser.parse_args()
    skills_root = Path(args.skills_root).expanduser().resolve()
    scripts = skills_root / "agentic-state-tools" / "scripts"
    py = sys.executable
    try:
        with tempfile.TemporaryDirectory(prefix="phongka-workflow-smoke-") as temp:
            root = Path(temp)
            route_cases = _route_smoke(py, scripts, root, _load_config(skills_root))
            runtime_cases = 0
            runtime_cases += _stateful_delivery_smoke(py, scripts, root)
            runtime_cases += _recovery_smoke(py, scripts, root)
            runtime_cases += _standalone_delivery_smoke(py, scripts, root)
    except (AssertionError, OSError, ValueError, KeyError, json.JSONDecodeError) as exc:
        print(json.dumps({"status": "FAILED", "error": str(exc)}, ensure_ascii=False, indent=2))
        return 1
    print(json.dumps({"status": "PASSED", "route_cases": route_cases, "runtime_cases": runtime_cases}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
