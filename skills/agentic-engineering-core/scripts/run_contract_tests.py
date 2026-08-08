"""Run adversarial contract tests for routing, planning, state, and evidence."""
from __future__ import annotations

import argparse
import copy
import hashlib
import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import Any


def run(
    command: list[str],
    expect: int = 0,
    env: dict[str, str] | None = None,
    cwd: Path | None = None,
) -> subprocess.CompletedProcess[str]:
    result = subprocess.run(
        command,
        text=True,
        capture_output=True,
        check=False,
        env=env,
        cwd=str(cwd) if cwd else None,
    )
    if result.returncode != expect:
        raise AssertionError(
            f"expected rc={expect}, got {result.returncode}: {' '.join(command)}\n"
            f"stdout:\n{result.stdout}\nstderr:\n{result.stderr}"
        )
    return result


def write(path: Path, value: Any) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, indent=2) + "\n", encoding="utf-8")
    return path


def parse(result: subprocess.CompletedProcess[str]) -> dict[str, Any]:
    value = json.loads(result.stdout)
    if not isinstance(value, dict):
        raise AssertionError("expected JSON object output")
    return value


def sha256_json(value: Any) -> str:
    canonical = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def decision(py: str, scripts: Path, project: Path, *, delivery: bool = False) -> Path:
    request = {
        "profile": "personal",
        "task_route": "feature",
        "execution_preference": "standard",
        "estimated_files": 1,
        "concerns": 1,
        "risk_flags": [],
        "user_requested_review": False,
        "delivery_action": "keep_local" if delivery else "none",
    }
    req = write(project / "request.json", request)
    out = project / "decision.json"
    run([py, str(scripts / "resolve_workflow.py"), "--input", str(req), "--output", str(out)])
    return out


def task_payload(
    status: str, scope: list[str], task_id: str = "TASK-1"
) -> dict[str, Any]:
    return {
        "task_id": task_id,
        "status": status,
        "summary": "bounded task",
        "scope": scope,
        "risk_flags": [],
    }


def context_payload(files: list[str]) -> dict[str, Any]:
    return {
        "schema_version": 3,
        "task_id": "TASK-1",
        "summary": "bounded context",
        "files": files,
        "constraints": ["use only explicitly listed files"],
    }


def handoff_payload(
    decision: dict[str, Any],
    *,
    status: str = "COMPLETED",
    attempt: int = 1,
    outcome: str = "NONE",
    evidence: str = "targeted evidence passed",
) -> dict[str, Any]:
    contract = decision["execution_contract"]
    return {
        "schema_version": 3,
        "task_id": "TASK-1",
        "status": status,
        "summary": "bounded handoff",
        "files_changed": ["src/a.txt"],
        "verification": [{"name": "contract", "status": "PASS", "evidence": evidence}],
        "risks": [],
        "execution_receipt": {
            "status": status,
            "task_id": "TASK-1",
            "workflow_decision_hash": decision["decision_hash"],
            "stage": "implement",
            "role": "agentic-implementer",
            "attempt": attempt,
            "max_attempts": contract["dispatch"]["max_total"],
            "repair_rounds": 0,
            "max_repair_rounds": contract["repair"]["max_repair_rounds"],
            "outcome": outcome,
            "evidence": evidence,
        },
    }


def setup_task(py: str, scripts: Path, project: Path, scope: list[str], *, delivery: bool = False) -> None:
    for rel in scope:
        target = project / rel
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(rel + "\n", encoding="utf-8")
    dec = decision(py, scripts, project, delivery=delivery)
    run([py, str(scripts / "init_runtime.py"), "--project-root", str(project), "--decision", str(dec)])
    inp = write(project / "task.json", task_payload("IN_PROGRESS", scope))
    run([py, str(scripts / "update_task_state.py"), "--project-root", str(project), "--input", str(inp)])


def setup_controlled_git_task(
    py: str, scripts: Path, project: Path, *, prepare: bool = True
) -> Path:
    target = project / "src/a.txt"
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text("initial\n", encoding="utf-8")
    run(["git", "init"], cwd=project)
    run(["git", "config", "user.email", "contract@example.invalid"], cwd=project)
    run(["git", "config", "user.name", "Contract Tests"], cwd=project)
    run(["git", "add", "src/a.txt"], cwd=project)
    run(["git", "commit", "-m", "initial"], cwd=project)
    request = {
        "profile": "personal",
        "task_route": "feature",
        "execution_preference": "controlled",
        "estimated_files": 1,
        "concerns": 1,
        "risk_flags": ["security_sensitive"],
        "user_requested_review": False,
        "delivery_action": "none",
    }
    request_path = write(project / "request.json", request)
    decision_path = project / "decision.json"
    run(
        [
            py,
            str(scripts / "resolve_workflow.py"),
            "--input",
            str(request_path),
            "--output",
            str(decision_path),
        ]
    )
    run(["git", "add", "request.json", "decision.json"], cwd=project)
    run(["git", "commit", "-m", "workflow decision"], cwd=project)
    run([py, str(scripts / "init_runtime.py"), "--project-root", str(project), "--decision", str(decision_path)])
    controlled_task = task_payload("IN_PROGRESS", ["src/a.txt"])
    controlled_task["risk_flags"] = ["security_sensitive"]
    controlled_task["approval_reference"] = "contract-approval"
    task_input = write(
        project / ".phongka" / "task-input.json",
        controlled_task,
    )
    run([py, str(scripts / "update_task_state.py"), "--project-root", str(project), "--input", str(task_input)])
    if prepare:
        run(
            [
                py,
                str(scripts / "prepare_worktree.py"),
                "--project-root",
                str(project),
                "--approval-reference",
                "contract-approval",
                "--decision",
                str(decision_path),
            ]
        )
    return decision_path


def workspace(py: str, scripts: Path, project: Path, paths: list[str]) -> dict[str, Any]:
    files: list[dict[str, Any]] = []
    identity: dict[str, Any] | None = None
    for rel in paths:
        result = parse(run([py, str(scripts / "capture_workspace.py"), "--project-root", str(project), "--path", rel]))
        files.extend(result["files"])
        if result.get("worktree") is not None:
            identity = result["worktree"]
    value: dict[str, Any] = {"files": files}
    if identity is not None:
        value["worktree"] = identity
    return value


def runtime_python(
    py: str,
    scripts: Path,
    project: Path,
    code: str,
    value: Any,
    *,
    expect: int = 0,
    env: dict[str, str] | None = None,
) -> subprocess.CompletedProcess[str]:
    return run(
        [py, "-c", code, str(project), str(scripts), json.dumps(value)],
        expect=expect,
        env=env,
    )


def criterion_results(rubric: dict[str, Any], *, status: str = "PASS") -> list[dict[str, str]]:
    return [
        {
            "id": criterion["id"],
            "status": status,
            "evidence": f"evidence for {criterion['id']}",
        }
        for criterion in rubric["criteria"]
    ]


def review_payload(rubrics: dict[str, Any], ws: dict[str, Any]) -> dict[str, Any]:
    rubric = rubrics["task"]
    return {
        "schema_version": 5,
        "task_id": "TASK-1",
        "review_mode": "task",
        "review_rubric_id": rubric["id"],
        "review_rubric_version": rubric["version"],
        "criteria": criterion_results(rubric),
        "outcome": "PASS",
        "summary": "review",
        "findings": [],
        "workspace": ws,
        "workspace_summary": "full-scope review",
    }


def batch_review_payload(rubrics: dict[str, Any], ws: dict[str, Any]) -> dict[str, Any]:
    rubric = rubrics["integration"]
    return {
        "schema_version": 3,
        "task_ids": ["TASK-1"],
        "review_mode": "integration",
        "review_rubric_id": rubric["id"],
        "review_rubric_version": rubric["version"],
        "criteria": criterion_results(rubric),
        "outcome": "PASS",
        "summary": "integration review",
        "findings": [],
        "workspace": ws,
        "workspace_summary": "full-scope integration review",
    }


def verification(ws: dict[str, Any], checks: list[str] | None = None) -> dict[str, Any]:
    ids = checks or ["A1", "A2"]
    return {
        "schema_version": 3,
        "task_id": "TASK-1",
        "status": "PASS",
        "checks": [{"name": item, "status": "PASS", "evidence": f"evidence {item}"} for item in ids],
        "workspace": ws,
        "workspace_summary": "fresh full-scope snapshot",
    }


def claim(ids: list[str]) -> dict[str, Any]:
    return {
        "schema_version": 3,
        "task_id": "TASK-1",
        "work_revision": 1,
        "claim": "task is complete",
        "acceptance": [{"id": item, "status": "PASS", "evidence": f"evidence {item}"} for item in ids],
        "verification_status": "PASS",
    }


def planning(scope: list[str], tasks: list[dict[str, Any]]) -> dict[str, Any]:
    return {
        "schema_version": 4,
        "review_rubric_id": "plan",
        "review_rubric_version": 1,
        "goal": "safe plan",
        "scope": scope,
        "tasks": tasks,
        "acceptance": ["done"],
        "verification": ["test"],
    }


def plan_task(
    task_id: str, files: list[str], deps: list[str], rubric: dict[str, Any]
) -> dict[str, Any]:
    return {
        "id": task_id,
        "review_rubric_id": rubric["id"],
        "review_rubric_version": rubric["version"],
        "objective": "change file",
        "files": files,
        "steps": ["edit"],
        "dependencies": deps,
        "acceptance": ["works"],
        "verification": ["test"],
        "rollback": "revert",
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--skills-root", required=True)
    args = parser.parse_args()
    skills = Path(args.skills_root).resolve()
    scripts = skills / "agentic-state-tools" / "scripts"
    config_script = skills / "agentic-configuration" / "scripts" / "load_config.py"
    settings_script = scripts / "load_runtime_settings.py"
    base_config = skills / "agentic-configuration" / "config" / "agentic-config.json"
    base_cfg = json.loads(base_config.read_text(encoding="utf-8"))
    rubrics = json.loads(
        (skills / "agentic-independent-reviewer" / "references" / "review-rubrics.json").read_text(
            encoding="utf-8"
        )
    )["rubrics"]
    shared_envelope = (
        skills / "agentic-engineering-core" / "prompts" / "subagent-envelope.md"
    ).read_text(encoding="utf-8").casefold()
    py = sys.executable
    passed: list[str] = []
    try:
        with tempfile.TemporaryDirectory(prefix="phongka-contract-tests-") as tmp:
            root = Path(tmp)

            routing = base_cfg["skill_routing"]
            core_skill = routing["process_skills"]["core"]
            companions = routing["required_companion_skills"]
            companion_prefix = [core_skill, *companions]
            state_skill = base_cfg["agents"]["agent-state-tools"]["skill"]
            for phrase in (
                "common contract",
                "shared role dispatch",
                "i-have-adhd",
                "not a workflow stage",
                "not an agent",
                "does not grant authority",
            ):
                assert phrase in shared_envelope
            configured_role_skills = routing["role_skills"]
            for route_name, skill_name in configured_role_skills.items():
                skill_path = (skills / skill_name / "SKILL.md").resolve()
                assert skills in skill_path.parents and skill_path.is_file(), (
                    f"configured role skill {route_name} has no discoverable SKILL.md: {skill_name}"
                )
            passed.append("shared_envelope_and_configured_role_skill_coverage")
            resolver_source = (scripts / "resolve_workflow.py").read_text(encoding="utf-8")
            assert "i-have-adhd" not in resolver_source
            passed.append("resolver_companion_name_is_generic")

            pressure_cases = [
                ("urgent_bounded", "quick_fix", "focused", 1),
                ("safety_stateless", "brainstorm", "focused", 0),
                ("harness_structured", "skill_authoring", "standard", 11),
            ]
            for name, route, depth, estimated_files in pressure_cases:
                request = {
                    "profile": "personal",
                    "task_route": route,
                    "execution_preference": depth,
                    "estimated_files": estimated_files,
                    "concerns": 1,
                    "risk_flags": [],
                    "user_requested_review": False,
                    "delivery_action": "none",
                }
                request_path = write(root / f"{name}.request.json", request)
                output_path = root / f"{name}.decision.json"
                result = parse(
                    run(
                        [
                            py,
                            str(scripts / "resolve_workflow.py"),
                            "--input",
                            str(request_path),
                            "--output",
                            str(output_path),
                        ]
                    )
                )
                assert result["required_skills"][: len(companion_prefix)] == companion_prefix
                if result["state_mode"] == "required":
                    assert result["required_skills"][len(companion_prefix)] == state_skill
                else:
                    assert state_skill not in result["required_skills"]
                stage_ids = {stage["id"] for stage in result["stages"]}
                stage_owners = {stage["owner"] for stage in result["stages"]}
                assert not stage_ids.intersection(companions)
                assert not stage_owners.intersection(companions)
                assert result["stages"][0]["owner"] == "primary"
                assert result["stages"][-1]["id"] == "report"
                assert result["stages"][-1]["owner"] == "primary"
            passed.append("required_companion_pressure_routes")

            invalid_companions = [
                ("missing_list", lambda cfg: cfg["skill_routing"].pop("required_companion_skills")),
                ("empty_list", lambda cfg: cfg["skill_routing"].update({"required_companion_skills": []})),
                ("malformed_list", lambda cfg: cfg["skill_routing"].update({"required_companion_skills": [1]})),
                ("duplicate", lambda cfg: cfg["skill_routing"].update({"required_companion_skills": companions * 2})),
                ("primary_self_reference", lambda cfg: cfg["skill_routing"].update({"required_companion_skills": [core_skill]})),
                ("missing_skill", lambda cfg: cfg["skill_routing"].update({"required_companion_skills": ["missing-companion-skill-for-contract"]})),
            ]
            for name, mutate in invalid_companions:
                invalid_cfg = copy.deepcopy(base_cfg)
                mutate(invalid_cfg)
                invalid_path = write(root / f"invalid-companion-{name}.json", invalid_cfg)
                run([py, str(config_script), "--config", str(invalid_path), "--check"], expect=1)
                passed.append(f"required_companion_{name}_rejected")

            settings_project = root / "runtime-settings"
            settings_decision = decision(py, scripts, settings_project)
            run(
                [
                    py,
                    str(scripts / "init_runtime.py"),
                    "--project-root",
                    str(settings_project),
                    "--decision",
                    str(settings_decision),
                ]
            )
            settings_path = settings_project / ".phongka" / "settings.json"
            central_wait = base_cfg["subagent_policy"]["wait"]
            created_settings = parse(
                run(
                    [
                        py,
                        str(settings_script),
                        "--project-root",
                        str(settings_project),
                    ]
                )
            )
            assert created_settings == {
                "schema_version": 1,
                "subagent_wait": central_wait,
            }
            passed.append("runtime_settings_created_from_central_defaults")

            user_settings = {
                "schema_version": 1,
                "subagent_wait": {
                    "check_interval_seconds": 45,
                    "timeout_seconds": 600,
                    "close_on_timeout": True,
                },
            }
            write(settings_path, user_settings)
            user_bytes = settings_path.read_bytes()
            assert parse(
                run(
                    [
                        py,
                        str(settings_script),
                        "--project-root",
                        str(settings_project),
                    ]
                )
            ) == user_settings
            run(
                [
                    py,
                    str(scripts / "init_runtime.py"),
                    "--project-root",
                    str(settings_project),
                    "--decision",
                    str(settings_decision),
                ]
            )
            assert settings_path.read_bytes() == user_bytes
            passed.append("runtime_settings_user_values_preserved")

            invalid_settings = copy.deepcopy(user_settings)
            invalid_settings["subagent_wait"]["check_interval_seconds"] = 60
            invalid_settings["subagent_wait"]["timeout_seconds"] = 60
            write(settings_path, invalid_settings)
            invalid_bytes = settings_path.read_bytes()
            run(
                [
                    py,
                    str(settings_script),
                    "--project-root",
                    str(settings_project),
                ],
                expect=1,
            )
            run(
                [
                    py,
                    str(scripts / "init_runtime.py"),
                    "--project-root",
                    str(settings_project),
                    "--decision",
                    str(settings_decision),
                ],
                expect=1,
            )
            assert settings_path.read_bytes() == invalid_bytes
            passed.append("invalid_runtime_settings_fail_closed")

            invalid_wait_cfg = copy.deepcopy(base_cfg)
            invalid_wait_cfg["subagent_policy"]["wait"]["check_interval_seconds"] = 60
            invalid_wait_cfg["subagent_policy"]["wait"]["timeout_seconds"] = 60
            invalid_wait_cfg_path = write(root / "invalid-wait-config.json", invalid_wait_cfg)
            run(
                [py, str(config_script), "--config", str(invalid_wait_cfg_path), "--check"],
                expect=1,
            )
            passed.append("invalid_central_wait_policy_rejected")

            persistence = root / "persistence-redaction"
            setup_task(py, scripts, persistence, ["src/a.txt"])
            nested_secret_values = {
                "task_id": "TASK-1",
                "details": [
                    {
                        "authorization": "Bearer abcdefghijklmnop",
                        "message": "ordinary prose about a secret remains usable",
                    },
                    {
                        "jwt_text": "eyJhbGciOiJIUzI1NiJ9.eyJzdWIiOiIxMjM0NTY3ODkwIn0.signaturevalue123",
                        "api_text": "sk-proj-abcdefghijklmnop",
                        "environment_text": "OPENAI_API_KEY=env-secret-value-123",
                    },
                    {"access_token": "nested-token-value"},
                ],
            }
            artifact_result = runtime_python(
                py,
                scripts,
                persistence,
                "import json,sys; sys.path.insert(0,sys.argv[2]); "
                "from artifact_writer import persist_artifact; "
                "print(json.dumps(persist_artifact(sys.argv[1], json.loads(sys.argv[3]), "
                "'nested.json', 'NESTED_WRITTEN')))" ,
                nested_secret_values,
            )
            persisted_artifact = json.loads(
                (persistence / ".phongka" / "artifacts" / "TASK-1" / "nested.json").read_text(
                    encoding="utf-8"
                )
            )
            artifact_text = json.dumps(persisted_artifact)
            for raw in (
                "Bearer abcdefghijklmnop",
                "eyJhbGciOiJIUzI1NiJ9.eyJzdWIiOiIxMjM0NTY3ODkwIn0.signaturevalue123",
                "sk-proj-abcdefghijklmnop",
                "env-secret-value-123",
                "nested-token-value",
            ):
                assert raw not in artifact_text
            assert persisted_artifact["details"][0]["message"] == (
                "ordinary prose about a secret remains usable"
            )
            assert "[REDACTED]" in artifact_text
            assert "[REDACTED]" in artifact_result.stdout
            passed.append("nested_artifact_secret_redaction")

            event_project = root / "event-redaction"
            event_secret_values = {
                "items": [
                    {"authorization": "Bearer event-token-abcdefghijkl"},
                    {"description": "the word secret is ordinary prose"},
                ],
                "api_key": "sk-live-abcdefghijklmnop",
            }
            runtime_python(
                py,
                scripts,
                event_project,
                "import json,sys; sys.path.insert(0,sys.argv[2]); "
                "from runtime_utils import append_event; "
                "append_event(sys.argv[1], 'TEST_EVENT', json.loads(sys.argv[3]))",
                event_secret_values,
            )
            event_text = (event_project / ".phongka" / "events.jsonl").read_text(
                encoding="utf-8"
            )
            for raw in ("Bearer event-token-abcdefghijkl", "sk-live-abcdefghijklmnop"):
                assert raw not in event_text
            assert "the word secret is ordinary prose" in event_text
            passed.append("event_secret_redaction")

            private_key = (
                "-----BEGIN PRIVATE KEY-----\n"
                "MIIEvQIBADANBgkqhkiG9w0BAQEFAASCBKc=\n"
                "-----END PRIVATE KEY-----"
            )
            private_result = runtime_python(
                py,
                scripts,
                persistence,
                "import json,sys; sys.path.insert(0,sys.argv[2]); "
                "from artifact_writer import persist_artifact; "
                "persist_artifact(sys.argv[1], json.loads(sys.argv[3]), 'private.json', 'PRIVATE')",
                {"task_id": "TASK-1", "key_material": private_key},
                expect=1,
            )
            assert private_key not in private_result.stderr
            assert not (persistence / ".phongka" / "artifacts" / "TASK-1" / "private.json").exists()
            passed.append("private_key_persistence_rejected")

            disabled_cfg = json.loads(base_config.read_text(encoding="utf-8"))
            disabled_cfg["security"]["redact_environment_values"] = False
            disabled_cfg["security"]["redact_tokens"] = False
            disabled_cfg_path = write(root / "redaction-disabled-config.json", disabled_cfg)
            disabled_project = root / "redaction-disabled"
            disabled_token = "Bearer disabled-token-abcdefghijkl"
            disabled_env = os.environ.copy()
            disabled_env["AGENTIC_CONFIG_FILE"] = str(disabled_cfg_path)
            disabled_result = runtime_python(
                py,
                scripts,
                disabled_project,
                "import json,sys; sys.path.insert(0,sys.argv[2]); "
                "from runtime_utils import append_event; "
                "append_event(sys.argv[1], 'DISABLED', json.loads(sys.argv[3]))",
                {"message": disabled_token},
                expect=1,
                env=disabled_env,
            )
            assert disabled_token not in disabled_result.stderr
            assert not (disabled_project / ".phongka" / "events.jsonl").exists()
            passed.append("redaction_disabled_secret_rejected")

            controlled = root / "controlled-worktree"
            controlled_decision_path = setup_controlled_git_task(py, scripts, controlled)
            controlled_decision = json.loads(controlled_decision_path.read_text(encoding="utf-8"))
            assert controlled_decision["worktree"]["required"] is True
            controlled_state = json.loads((controlled / ".phongka" / "state.json").read_text(encoding="utf-8"))
            controlled_task = json.loads(
                (controlled / ".phongka" / "tasks" / "TASK-1.json").read_text(encoding="utf-8")
            )
            identity = controlled_state["worktree_identity"]
            assert identity == controlled_task["worktree_identity"]
            worktree_path = controlled / identity["path"]
            assert worktree_path.is_dir()
            assert identity["branch"] in run(["git", "branch", "--show-current"], cwd=worktree_path).stdout
            assert identity["head_commit"] == run(["git", "rev-parse", "HEAD"], cwd=worktree_path).stdout.strip()
            controlled_workspace = workspace(py, scripts, controlled, ["src/a.txt"])
            assert controlled_workspace["worktree"] == identity
            assert (worktree_path / "src/a.txt").read_text(encoding="utf-8") == "initial\n"
            passed.append("controlled_worktree_prepared_and_bound")

            unapproved = root / "worktree-approval"
            setup_controlled_git_task(py, scripts, unapproved, prepare=False)
            run(
                [
                    py,
                    str(scripts / "prepare_worktree.py"),
                    "--project-root",
                    str(unapproved),
                    "--approval-reference",
                    "wrong-approval",
                ],
                expect=1,
            )
            assert not (unapproved / ".phongka" / "worktrees" / "TASK-1").exists()
            passed.append("worktree_approval_boundary_rejected")

            path_mismatch = copy.deepcopy(controlled_workspace)
            path_mismatch["worktree"]["path"] = ".phongka/worktrees/other-task"
            runtime_python(
                py,
                scripts,
                controlled,
                "import json,sys; sys.path.insert(0,sys.argv[2]); "
                "from runtime_utils import verify_workspace_snapshot; "
                "verify_workspace_snapshot(sys.argv[1], json.loads(sys.argv[3]), 'TASK-1')",
                path_mismatch,
                expect=1,
            )
            passed.append("worktree_path_mismatch_rejected")

            branch_mismatch = root / "worktree-branch-mismatch"
            setup_controlled_git_task(py, scripts, branch_mismatch)
            branch_identity = json.loads(
                (branch_mismatch / ".phongka" / "state.json").read_text(encoding="utf-8")
            )["worktree_identity"]
            branch_path = branch_mismatch / branch_identity["path"]
            run(["git", "branch", "-m", "phongka/task/TASK-1-tampered"], cwd=branch_path)
            branch_recovery = parse(
                run([py, str(scripts / "inspect_recovery.py"), "--project-root", str(branch_mismatch)])
            )
            assert branch_recovery["status"] == "RECOVERY_REQUIRED"
            assert branch_recovery["next_action"] == "INSPECT_WORKTREE_BRANCH"
            passed.append("worktree_branch_mismatch_recovery")

            head_mismatch = root / "worktree-head-mismatch"
            setup_controlled_git_task(py, scripts, head_mismatch)
            head_identity = json.loads(
                (head_mismatch / ".phongka" / "state.json").read_text(encoding="utf-8")
            )["worktree_identity"]
            head_path = head_mismatch / head_identity["path"]
            (head_path / "src/a.txt").write_text("divergent\n", encoding="utf-8")
            run(["git", "add", "src/a.txt"], cwd=head_path)
            run(["git", "commit", "-m", "divergent"], cwd=head_path)
            head_recovery = parse(
                run([py, str(scripts / "inspect_recovery.py"), "--project-root", str(head_mismatch)])
            )
            assert head_recovery["status"] == "RECOVERY_REQUIRED"
            assert head_recovery["next_action"] == "INSPECT_WORKTREE_HEAD"
            passed.append("worktree_head_mismatch_recovery")

            dirty = root / "worktree-dirty"
            setup_controlled_git_task(py, scripts, dirty)
            dirty_identity = json.loads(
                (dirty / ".phongka" / "state.json").read_text(encoding="utf-8")
            )["worktree_identity"]
            (dirty / dirty_identity["path"] / "src/a.txt").write_text("dirty\n", encoding="utf-8")
            dirty_recovery = parse(
                run([py, str(scripts / "inspect_recovery.py"), "--project-root", str(dirty)])
            )
            assert dirty_recovery["status"] == "RECOVERY_REQUIRED"
            assert dirty_recovery["next_action"] == "RECONCILE_WORKTREE_DIRTY"
            passed.append("worktree_dirty_recovery")

            cfg = copy.deepcopy(base_cfg)
            cfg["default_profile"] = "high_risk"
            cfg["subagent_policy"]["wait"] = {
                "check_interval_seconds": 90,
                "timeout_seconds": 900,
                "close_on_timeout": True,
            }
            cfg_path = write(root / "high-risk-config.json", cfg)
            result = parse(run([py, str(scripts / "resolve_workflow.py"), "--config", str(cfg_path)]))
            assert result["profile_id"] == "high_risk"
            passed.append("default_profile_honored")

            custom_runtime = root / "custom-config-runtime"
            custom_decision = custom_runtime / "decision.json"
            run(
                [
                    py,
                    str(scripts / "resolve_workflow.py"),
                    "--config",
                    str(cfg_path),
                    "--output",
                    str(custom_decision),
                ]
            )
            run(
                [
                    py,
                    str(scripts / "init_runtime.py"),
                    "--project-root",
                    str(custom_runtime),
                    "--decision",
                    str(custom_decision),
                ],
                expect=1,
            )
            run(
                [
                    py,
                    str(scripts / "init_runtime.py"),
                    "--project-root",
                    str(custom_runtime),
                    "--decision",
                    str(custom_decision),
                    "--config",
                    str(cfg_path),
                ]
            )
            custom_settings = parse(
                run(
                    [
                        py,
                        str(settings_script),
                        "--project-root",
                        str(custom_runtime),
                    ]
                )
            )
            assert custom_settings["subagent_wait"] == cfg["subagent_policy"]["wait"]
            passed.append("decision_requires_matching_config")
            passed.append("custom_config_wait_defaults_used")

            bad_cfg = copy.deepcopy(cfg)
            bad_cfg["default_profile"] = "does_not_exist"
            bad_cfg_path = write(root / "bad-config.json", bad_cfg)
            run([py, str(config_script), "--config", str(bad_cfg_path), "--check"], expect=1)
            passed.append("missing_default_profile_rejected")

            auth = root / "decision-authenticity"
            auth_decision = decision(py, scripts, auth)
            tampered = json.loads(auth_decision.read_text(encoding="utf-8"))
            tampered["approval"] = {
                "required": False,
                "kind": "automatic",
                "keys": ["normal_change"],
                "reasons": ["tampered policy"],
            }
            tampered["decision_hash"] = sha256_json(
                {key: value for key, value in tampered.items() if key != "decision_hash"}
            )
            write(auth_decision, tampered)
            run(
                [
                    py,
                    str(scripts / "init_runtime.py"),
                    "--project-root",
                    str(auth),
                    "--decision",
                    str(auth_decision),
                ],
                expect=1,
            )
            passed.append("policy_inconsistent_decision_rejected")

            optional_cfg = copy.deepcopy(cfg)
            optional_cfg["runtime"]["standard_state"] = "optional"
            optional_cfg_path = write(root / "optional-state-config.json", optional_cfg)
            optional = parse(
                run(
                    [
                        py,
                        str(scripts / "resolve_workflow.py"),
                        "--config",
                        str(optional_cfg_path),
                        "--profile",
                        "personal",
                        "--task-route",
                        "feature",
                        "--execution",
                        "standard",
                        "--estimated-files",
                        "2",
                        "--concerns",
                        "1",
                    ]
                )
            )
            assert optional["state_mode"] == "optional"
            assert optional["runtime_actions"] == {"before": [], "after": []}
            assert optional["worktree"]["required"] is False
            assert optional["limits"]["max_context_bytes"] == 262144
            assert optional["limits"]["max_context_bytes"] == optional["context_budget"]["max_bytes"]
            dispatch = optional["execution_contract"]["dispatch"]
            assert {
                "max_active",
                "max_total",
                "max_parallel_writers",
                "fresh_context_per_dispatch",
                "synthesized_fallback",
            } <= set(dispatch)
            repair = optional["execution_contract"]["repair"]
            assert {"max_repair_rounds", "re_review_required"} <= set(repair)
            assert optional["execution_contract"]["receipt"]["fallback_values"] == [
                "NONE",
                "SYNTHESIZED FALLBACK",
                "BLOCKED",
            ]
            passed.append("decision_context_dispatch_receipt_contract")

            context_project = root / "bounded-context"
            setup_task(py, scripts, context_project, ["src/a.txt"])
            context_decision = context_project / "decision.json"
            valid_context = write(context_project / "context-input.json", context_payload(["src/a.txt"]))
            run(
                [
                    py,
                    str(scripts / "create_context.py"),
                    "--project-root",
                    str(context_project),
                    "--input",
                    str(valid_context),
                    "--decision",
                    str(context_decision),
                ]
            )
            persisted_context = json.loads(
                (context_project / ".phongka" / "artifacts" / "TASK-1" / "context.json").read_text()
            )
            assert persisted_context["file_count"] == 1, persisted_context
            assert persisted_context["byte_count"] == len((context_project / "src/a.txt").read_bytes()), persisted_context
            passed.append("context_summary_persisted")

            too_many = context_project / "too-many"
            too_many_files = ["src/a.txt"]
            for index in range(20):
                rel = f"src/extra-{index}.txt"
                target = too_many / rel
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_text(rel + "\n", encoding="utf-8")
                too_many_files.append(rel)
            too_many_input = write(too_many / "context-input.json", context_payload(too_many_files))
            run(
                [
                    py,
                    str(scripts / "create_context.py"),
                    "--project-root",
                    str(too_many),
                    "--input",
                    str(too_many_input),
                    "--decision",
                    str(context_decision),
                ],
                expect=1,
            )
            passed.append("context_file_overflow_rejected")

            byte_project = root / "oversize-context"
            setup_task(py, scripts, byte_project, ["src/a.txt"])
            large = byte_project / "src/large.bin"
            large.write_bytes(b"x" * 262145)
            byte_input = write(byte_project / "context-input.json", context_payload(["src/large.bin"]))
            run(
                [
                    py,
                    str(scripts / "create_context.py"),
                    "--project-root",
                    str(byte_project),
                    "--input",
                    str(byte_input),
                    "--decision",
                    str(byte_project / "decision.json"),
                ],
                expect=1,
            )
            passed.append("context_byte_overflow_rejected")

            env_config = copy.deepcopy(json.loads(base_config.read_text()))
            env_config["context_budget"]["max_bytes"] = 16
            env_config_path = write(root / "env-context-config.json", env_config)
            env_context = root / "env-context"
            (env_context / "src").mkdir(parents=True)
            (env_context / "src" / "a.txt").write_text("x" * 17, encoding="utf-8")
            env_decision = env_context / "decision.json"
            env_request = write(
                env_context / "request.json",
                {
                    "profile": "personal",
                    "task_route": "feature",
                    "execution_preference": "standard",
                    "estimated_files": 1,
                    "concerns": 1,
                    "risk_flags": [],
                    "user_requested_review": False,
                    "delivery_action": "none",
                },
            )
            run(
                [
                    py,
                    str(scripts / "resolve_workflow.py"),
                    "--config",
                    str(env_config_path),
                    "--input",
                    str(env_request),
                    "--output",
                    str(env_decision),
                ]
            )
            env_input = write(env_context / "context-input.json", context_payload(["src/a.txt"]))
            env = os.environ.copy()
            env["AGENTIC_CONFIG_FILE"] = str(env_config_path)
            run(
                [
                    py,
                    str(scripts / "create_context.py"),
                    "--project-root",
                    str(env_context),
                    "--input",
                    str(env_input),
                    "--decision",
                    str(env_decision),
                ],
                expect=1,
                env=env,
            )
            passed.append("context_honors_agentic_config_file")

            handoff_project = root / "receipt-contract"
            setup_task(py, scripts, handoff_project, ["src/a.txt"])
            handoff_decision_path = handoff_project / "decision.json"
            handoff_decision = json.loads(handoff_decision_path.read_text())
            valid_handoff = write(
                handoff_project / "handoff-input.json", handoff_payload(handoff_decision)
            )
            run(
                [
                    py,
                    str(scripts / "create_handoff.py"),
                    "--project-root",
                    str(handoff_project),
                    "--input",
                    str(valid_handoff),
                    "--decision",
                    str(handoff_decision_path),
                ]
            )
            passed.append("receipt_validated_and_bound")

            bad_binding = handoff_payload(handoff_decision)
            bad_binding["execution_receipt"]["workflow_decision_hash"] = "0" * 64
            run(
                [
                    py,
                    str(scripts / "create_handoff.py"),
                    "--project-root",
                    str(handoff_project),
                    "--input",
                    str(write(handoff_project / "bad-binding.json", bad_binding)),
                    "--decision",
                    str(handoff_decision_path),
                ],
                expect=1,
            )
            passed.append("receipt_decision_binding_rejected")

            over_attempt = handoff_payload(
                handoff_decision,
                attempt=handoff_decision["execution_contract"]["dispatch"]["max_total"] + 1,
            )
            run(
                [
                    py,
                    str(scripts / "create_handoff.py"),
                    "--project-root",
                    str(handoff_project),
                    "--input",
                    str(write(handoff_project / "over-attempt.json", over_attempt)),
                    "--decision",
                    str(handoff_decision_path),
                ],
                expect=1,
            )
            passed.append("receipt_attempt_overflow_rejected")

            fallback = handoff_payload(
                handoff_decision, outcome="SYNTHESIZED FALLBACK", evidence="primary synthesized fallback evidence"
            )
            run(
                [
                    py,
                    str(scripts / "create_handoff.py"),
                    "--project-root",
                    str(handoff_project),
                    "--input",
                    str(write(handoff_project / "fallback.json", fallback)),
                    "--decision",
                    str(handoff_decision_path),
                ]
            )
            blocked_mismatch = handoff_payload(handoff_decision, outcome="BLOCKED")
            run(
                [
                    py,
                    str(scripts / "create_handoff.py"),
                    "--project-root",
                    str(handoff_project),
                    "--input",
                    str(write(handoff_project / "blocked-mismatch.json", blocked_mismatch)),
                    "--decision",
                    str(handoff_decision_path),
                ],
                expect=1,
            )
            passed.append("receipt_fallback_and_blocked_semantics_checked")
            passed.append("optional_state_has_no_implicit_runtime_actions")

            bad_plan = write(
                root / "escape-plan.json",
                planning(
                    ["../outside.py"],
                    [plan_task("T1", ["../outside.py"], [], rubrics["task"])],
                ),
            )
            run([py, str(scripts / "validate_planning.py"), "--input", str(bad_plan)], expect=1)
            passed.append("plan_path_escape_rejected")

            conflict = write(
                root / "conflict-plan.json",
                planning(
                    ["src/a.py"],
                    [
                        plan_task("T1", ["src/a.py"], [], rubrics["task"]),
                        plan_task("T2", ["src/a.py"], [], rubrics["task"]),
                    ],
                ),
            )
            run([py, str(scripts / "validate_planning.py"), "--input", str(conflict)], expect=1)
            ordered = write(
                root / "ordered-plan.json",
                planning(
                    ["src/a.py"],
                    [
                        plan_task("T1", ["src/a.py"], [], rubrics["task"]),
                        plan_task("T2", ["src/a.py"], ["T1"], rubrics["task"]),
                    ],
                ),
            )
            run([py, str(scripts / "validate_planning.py"), "--input", str(ordered)])
            passed.append("shared_file_requires_dependency_order")

            missing_task_rubric = planning(
                ["src/a.py"],
                [plan_task("T1", ["src/a.py"], [], rubrics["task"])],
            )
            missing_task_rubric["tasks"][0].pop("review_rubric_id")
            missing_plan_path = write(root / "missing-task-rubric.json", missing_task_rubric)
            run(
                [py, str(scripts / "validate_planning.py"), "--input", str(missing_plan_path)],
                expect=1,
            )
            passed.append("missing_task_review_rubric_rejected")

            missing_plan_rubric = planning(
                ["src/a.py"],
                [plan_task("T1", ["src/a.py"], [], rubrics["task"])],
            )
            missing_plan_rubric.pop("review_rubric_id")
            missing_plan_path = write(root / "missing-plan-rubric.json", missing_plan_rubric)
            run(
                [py, str(scripts / "validate_planning.py"), "--input", str(missing_plan_path)],
                expect=1,
            )
            passed.append("missing_plan_review_rubric_rejected")

            wrong_plan_rubric = planning(
                ["src/a.py"],
                [plan_task("T1", ["src/a.py"], [], rubrics["task"])],
            )
            wrong_plan_rubric["review_rubric_id"] = "task"
            wrong_plan_path = write(root / "task-rubric-for-plan.json", wrong_plan_rubric)
            run(
                [py, str(scripts / "validate_planning.py"), "--input", str(wrong_plan_path)],
                expect=1,
            )
            passed.append("task_rubric_not_allowed_for_plan_bundle")

            wrong_task_rubric = planning(
                ["src/a.py"],
                [plan_task("T1", ["src/a.py"], [], rubrics["plan"])],
            )
            wrong_task_path = write(root / "plan-rubric-for-task.json", wrong_task_rubric)
            run(
                [py, str(scripts / "validate_planning.py"), "--input", str(wrong_task_path)],
                expect=1,
            )
            passed.append("plan_rubric_not_allowed_for_planned_task")

            capture = root / "capture-normalization"
            (capture / "src").mkdir(parents=True)
            (capture / "src" / "a.txt").write_text("a\n", encoding="utf-8")
            run(
                [
                    py,
                    str(scripts / "capture_workspace.py"),
                    "--project-root",
                    str(capture),
                    "--path",
                    "src/a.txt",
                    "--path",
                    "src/./a.txt",
                ],
                expect=1,
            )
            passed.append("duplicate_normalized_workspace_paths_rejected")

            migration = root / "migration"
            migration.mkdir()
            (migration / ".agent").write_text("not a directory", encoding="utf-8")
            run(
                [py, str(scripts / "migrate_runtime_root.py"), "--project-root", str(migration), "--apply"],
                expect=1,
            )
            passed.append("invalid_legacy_runtime_rejected_cleanly")

            project = root / "unknown-fields"
            setup_task(py, scripts, project, ["src/a.txt"])
            bad_task = task_payload("IN_PROGRESS", ["src/a.txt"])
            bad_task["unexpected"] = True
            run([py, str(scripts / "update_task_state.py"), "--project-root", str(project), "--input", str(write(project / "bad-task.json", bad_task))], expect=1)
            passed.append("unknown_task_fields_rejected")

            orphan = root / "orphan"
            dec = decision(py, scripts, orphan)
            run([py, str(scripts / "init_runtime.py"), "--project-root", str(orphan), "--decision", str(dec)])
            write(orphan / ".phongka" / "tasks" / "ORPHAN.json", {"invalid": True})
            run([py, str(scripts / "validate_state.py"), "--project-root", str(orphan)], expect=1)
            recovery = parse(run([py, str(scripts / "inspect_recovery.py"), "--project-root", str(orphan)]))
            assert recovery["next_action"] == "RECONCILE_TASK_INDEX"
            passed.append("orphan_task_index_detected")

            inconsistent = root / "inconsistent-runtime"
            setup_task(py, scripts, inconsistent, ["src/a.txt"])
            inconsistent_state_path = inconsistent / ".phongka" / "state.json"
            inconsistent_state = json.loads(inconsistent_state_path.read_text(encoding="utf-8"))
            inconsistent_state["status"] = "IDLE"
            write(inconsistent_state_path, inconsistent_state)
            recovery = parse(
                run(
                    [py, str(scripts / "inspect_recovery.py"), "--project-root", str(inconsistent)]
                )
            )
            assert recovery["next_action"] == "RECONCILE_RUNTIME_STATE"
            passed.append("recovery_runtime_invariant_detected")

            case_ids = root / "case-insensitive-task-ids"
            (case_ids / "src").mkdir(parents=True)
            (case_ids / "src/a.txt").write_text("a\n", encoding="utf-8")
            case_decision = decision(py, scripts, case_ids)
            run(
                [
                    py,
                    str(scripts / "init_runtime.py"),
                    "--project-root",
                    str(case_ids),
                    "--decision",
                    str(case_decision),
                ]
            )
            run(
                [
                    py,
                    str(scripts / "update_task_state.py"),
                    "--project-root",
                    str(case_ids),
                    "--input",
                    str(write(case_ids / "task-open.json", task_payload("IN_PROGRESS", ["src/a.txt"], "Task"))),
                ]
            )
            run(
                [
                    py,
                    str(scripts / "update_task_state.py"),
                    "--project-root",
                    str(case_ids),
                    "--input",
                    str(write(case_ids / "task-complete.json", task_payload("COMPLETED", ["src/a.txt"], "Task"))),
                ]
            )
            run(
                [
                    py,
                    str(scripts / "update_task_state.py"),
                    "--project-root",
                    str(case_ids),
                    "--input",
                    str(write(case_ids / "task-variant.json", task_payload("ACCEPTED", ["src/a.txt"], "task"))),
                ],
                expect=1,
            )
            passed.append("case_insensitive_task_id_collision_rejected")

            partial = root / "partial-scope"
            setup_task(py, scripts, partial, ["src/a.txt", "src/b.txt"])
            partial_ws = workspace(py, scripts, partial, ["src/a.txt"])
            review = review_payload(rubrics, partial_ws)
            run([py, str(scripts / "create_review.py"), "--project-root", str(partial), "--input", str(write(partial / "review.json", review))], expect=1)
            run([py, str(scripts / "record_verification_evidence.py"), "--project-root", str(partial), "--input", str(write(partial / "verify.json", verification(partial_ws)))], expect=1)
            passed.append("full_scope_evidence_required")

            rubric_contract = root / "rubric-contracts"
            setup_task(py, scripts, rubric_contract, ["src/a.txt"])
            rubric_ws = workspace(py, scripts, rubric_contract, ["src/a.txt"])
            valid_review = review_payload(rubrics, rubric_ws)
            missing_rubric = copy.deepcopy(valid_review)
            missing_rubric.pop("review_rubric_id")
            run(
                [
                    py,
                    str(scripts / "create_review.py"),
                    "--project-root",
                    str(rubric_contract),
                    "--input",
                    str(write(rubric_contract / "missing-rubric.json", missing_rubric)),
                ],
                expect=1,
            )
            passed.append("missing_review_rubric_rejected")

            incomplete_criteria = copy.deepcopy(valid_review)
            incomplete_criteria["criteria"] = incomplete_criteria["criteria"][:-1]
            run(
                [
                    py,
                    str(scripts / "create_review.py"),
                    "--project-root",
                    str(rubric_contract),
                    "--input",
                    str(write(rubric_contract / "incomplete-criteria.json", incomplete_criteria)),
                ],
                expect=1,
            )
            passed.append("incomplete_review_criteria_rejected")

            unknown_criteria = copy.deepcopy(valid_review)
            unknown_criteria["criteria"][0]["id"] = "unknown_criterion"
            run(
                [
                    py,
                    str(scripts / "create_review.py"),
                    "--project-root",
                    str(rubric_contract),
                    "--input",
                    str(write(rubric_contract / "unknown-criterion.json", unknown_criteria)),
                ],
                expect=1,
            )
            passed.append("unknown_review_criterion_rejected")

            duplicate_criteria = copy.deepcopy(valid_review)
            duplicate_criteria["criteria"].append(copy.deepcopy(duplicate_criteria["criteria"][0]))
            duplicate_criteria["criteria"][-1]["evidence"] = "duplicate criterion id"
            run(
                [
                    py,
                    str(scripts / "create_review.py"),
                    "--project-root",
                    str(rubric_contract),
                    "--input",
                    str(write(rubric_contract / "duplicate-criterion.json", duplicate_criteria)),
                ],
                expect=1,
            )
            passed.append("duplicate_review_criterion_rejected")

            failed_criteria = copy.deepcopy(valid_review)
            failed_criteria["criteria"][0]["status"] = "FAIL"
            run(
                [
                    py,
                    str(scripts / "create_review.py"),
                    "--project-root",
                    str(rubric_contract),
                    "--input",
                    str(write(rubric_contract / "failed-criterion-pass.json", failed_criteria)),
                ],
                expect=1,
            )
            passed.append("pass_with_failed_review_criterion_rejected")

            valid_batch = batch_review_payload(rubrics, rubric_ws)
            run(
                [
                    py,
                    str(scripts / "create_batch_review.py"),
                    "--project-root",
                    str(rubric_contract),
                    "--input",
                    str(write(rubric_contract / "valid-batch.json", valid_batch)),
                ]
            )
            batch_token = "Bearer batch-token-abcdefghijkl"
            secret_batch = copy.deepcopy(valid_batch)
            secret_batch["summary"] = batch_token
            run(
                [
                    py,
                    str(scripts / "create_batch_review.py"),
                    "--project-root",
                    str(rubric_contract),
                    "--input",
                    str(write(rubric_contract / "secret-batch.json", secret_batch)),
                ]
            )
            persisted_batch = (rubric_contract / ".phongka" / "batch-review.json").read_text(
                encoding="utf-8"
            )
            assert batch_token not in persisted_batch
            assert "[REDACTED]" in persisted_batch
            passed.append("batch_review_secret_redaction")
            unknown_batch = copy.deepcopy(valid_batch)
            unknown_batch["criteria"][0]["id"] = "unknown_criterion"
            run(
                [
                    py,
                    str(scripts / "create_batch_review.py"),
                    "--project-root",
                    str(rubric_contract),
                    "--input",
                    str(write(rubric_contract / "unknown-batch-criterion.json", unknown_batch)),
                ],
                expect=1,
            )
            passed.append("unknown_integration_criterion_rejected")

            mapping = root / "mapping"
            setup_task(py, scripts, mapping, ["src/a.txt"])
            ws = workspace(py, scripts, mapping, ["src/a.txt"])
            run([py, str(scripts / "record_verification_evidence.py"), "--project-root", str(mapping), "--input", str(write(mapping / "verify.json", verification(ws)))])
            run([py, str(scripts / "update_task_state.py"), "--project-root", str(mapping), "--input", str(write(mapping / "complete.json", task_payload("COMPLETED", ["src/a.txt"])))])
            run([py, str(scripts / "verify_completion_claim.py"), "--project-root", str(mapping), "--input", str(write(mapping / "bad-claim.json", claim(["X1", "X2"])))], expect=1)
            run([py, str(scripts / "verify_completion_claim.py"), "--project-root", str(mapping), "--input", str(write(mapping / "claim.json", claim(["A1", "A2"])))])
            passed.append("acceptance_ids_match_verification_checks")

            duplicate = root / "duplicate-checks"
            setup_task(py, scripts, duplicate, ["src/a.txt"])
            dup_ws = workspace(py, scripts, duplicate, ["src/a.txt"])
            run([py, str(scripts / "record_verification_evidence.py"), "--project-root", str(duplicate), "--input", str(write(duplicate / "verify.json", verification(dup_ws, ["A1", "A1"])))], expect=1)
            passed.append("duplicate_verification_ids_rejected")

            blank = root / "blank-evidence-ids"
            setup_task(py, scripts, blank, ["src/a.txt"])
            blank_ws = workspace(py, scripts, blank, ["src/a.txt"])
            run(
                [
                    py,
                    str(scripts / "record_verification_evidence.py"),
                    "--project-root",
                    str(blank),
                    "--input",
                    str(write(blank / "blank-verify.json", verification(blank_ws, [" "]))),
                ],
                expect=1,
            )
            run(
                [
                    py,
                    str(scripts / "record_verification_evidence.py"),
                    "--project-root",
                    str(blank),
                    "--input",
                    str(write(blank / "valid-verify.json", verification(blank_ws))),
                ]
            )
            run(
                [
                    py,
                    str(scripts / "update_task_state.py"),
                    "--project-root",
                    str(blank),
                    "--input",
                    str(write(blank / "complete.json", task_payload("COMPLETED", ["src/a.txt"]))),
                ]
            )
            run(
                [
                    py,
                    str(scripts / "verify_completion_claim.py"),
                    "--project-root",
                    str(blank),
                    "--input",
                    str(write(blank / "blank-claim.json", claim([" "]))),
                ],
                expect=1,
            )
            passed.append("blank_evidence_ids_rejected")

            unsupported = root / "unsupported-schema"
            unsupported_schema = write(
                unsupported / "schema.json",
                {"type": "object", "oneOf": [{"type": "object"}]},
            )
            unsupported_input = write(unsupported / "input.json", {})
            run(
                [
                    py,
                    str(scripts / "validate_schema.py"),
                    "--input",
                    str(unsupported_input),
                    "--schema",
                    str(unsupported_schema),
                ],
                expect=1,
            )
            passed.append("unsupported_schema_keyword_rejected")
            unsupported_properties_schema = write(
                unsupported / "unsupported-properties-schema.json",
                {"type": "object", "minProperties": 1},
            )
            run(
                [
                    py,
                    str(scripts / "validate_schema.py"),
                    "--input",
                    str(unsupported_input),
                    "--schema",
                    str(unsupported_properties_schema),
                ],
                expect=1,
            )
            passed.append("unsupported_schema_constraints_rejected")

            todo = root / "todo-evidence"
            (todo / "src").mkdir(parents=True)
            (todo / "src/a.txt").write_text("a\n")
            dec = decision(py, scripts, todo)
            run([py, str(scripts / "init_runtime.py"), "--project-root", str(todo), "--decision", str(dec)])
            run([py, str(scripts / "update_task_state.py"), "--project-root", str(todo), "--input", str(write(todo / "task.json", task_payload("TODO", ["src/a.txt"])))])
            todo_ws = workspace(py, scripts, todo, ["src/a.txt"])
            run([py, str(scripts / "record_verification_evidence.py"), "--project-root", str(todo), "--input", str(write(todo / "verify.json", verification(todo_ws)))], expect=1)
            passed.append("evidence_status_boundary_enforced")

            integrity = root / "claim-integrity"
            setup_task(py, scripts, integrity, ["src/a.txt"], delivery=True)
            integrity_ws = workspace(py, scripts, integrity, ["src/a.txt"])
            run([py, str(scripts / "record_verification_evidence.py"), "--project-root", str(integrity), "--input", str(write(integrity / "verify.json", verification(integrity_ws)))])
            run([py, str(scripts / "update_task_state.py"), "--project-root", str(integrity), "--input", str(write(integrity / "complete.json", task_payload("COMPLETED", ["src/a.txt"])))])
            run([py, str(scripts / "verify_completion_claim.py"), "--project-root", str(integrity), "--input", str(write(integrity / "claim.json", claim(["A1", "A2"])))])
            persisted = integrity / ".phongka" / "artifacts" / "TASK-1" / "completion-claim.json"
            tampered = json.loads(persisted.read_text())
            tampered["claim"] = "tampered"
            write(persisted, tampered)
            delivery_payload = {
                "schema_version": 4,
                "task_ids": ["TASK-1"],
                "action": "keep_local",
                "outcome": "KEEP_LOCAL",
                "summary": "deliver",
                "approval_reference": None,
                "cleanup": "KEEP",
            }
            run([py, str(scripts / "finalize_delivery.py"), "--project-root", str(integrity), "--input", str(write(integrity / "delivery.json", delivery_payload))], expect=1)
            passed.append("completion_claim_hash_rechecked_at_delivery")

            checklist = root / "checklist-auto-refresh"
            setup_task(py, scripts, checklist, ["src/a.txt"])
            checklist_ws = workspace(py, scripts, checklist, ["src/a.txt"])
            run([py, str(scripts / "create_review.py"), "--project-root", str(checklist), "--input", str(write(checklist / "review.json", review_payload(rubrics, checklist_ws)))])
            run([py, str(scripts / "record_verification_evidence.py"), "--project-root", str(checklist), "--input", str(write(checklist / "verify.json", verification(checklist_ws)))])
            checklist_dir = checklist / ".phongka" / "checklist"
            checklist_task_1 = checklist_dir / "task-checklist-TASK-1.md"
            if not checklist_task_1.is_file():
                raise AssertionError("task-specific checklist was not refreshed after review/verify")
            if (checklist_dir / "README.md").exists():
                raise AssertionError("generic checklist README must not be generated")
            initial_text = checklist_task_1.read_text(encoding="utf-8")
            if "Current stage: `unknown`" not in initial_text:
                raise AssertionError("checklist guessed a stage without a valid marker")
            if any(
                line.startswith("- [x]")
                for line in initial_text.splitlines()
                if "`" in line and " - " in line
            ):
                raise AssertionError("checklist marked a stage reached without a valid marker")

            complete = task_payload("COMPLETED", ["src/a.txt"])
            run([py, str(scripts / "update_task_state.py"), "--project-root", str(checklist), "--input", str(write(checklist / "complete.json", complete))])
            completed_state = json.loads((checklist / ".phongka" / "state.json").read_text(encoding="utf-8"))
            if completed_state["active_task_id"] is not None:
                raise AssertionError("terminal task must clear active_task_id")
            completed_text = checklist_task_1.read_text(encoding="utf-8")
            if "Task status: `COMPLETED`" not in completed_text:
                raise AssertionError("terminal refresh did not preserve the completed task context")

            decision_data = json.loads((checklist / "decision.json").read_text(encoding="utf-8"))
            stage_ids = [stage["id"] for stage in decision_data["stages"]]
            current_stage = "verify"
            current_index = stage_ids.index(current_stage)
            run(
                [
                    py,
                    str(scripts / "render_checklist.py"),
                    "--project-root",
                    str(checklist),
                    "--task-id",
                    "TASK-1",
                    "--current-stage",
                    current_stage,
                    "--current-skill",
                    "agentic-verification-before-completion",
                ]
            )
            reached_text = checklist_task_1.read_text(encoding="utf-8")
            for index, stage_id in enumerate(stage_ids):
                marker = next(
                    (line for line in reached_text.splitlines() if f"`{stage_id}` - " in line),
                    None,
                )
                expected = "[x]" if index <= current_index else "[ ]"
                if marker is None or not marker.startswith(f"- {expected}"):
                    raise AssertionError(f"stage {stage_id} did not render reached progress")
            if "reached, not completion" not in reached_text:
                raise AssertionError("checklist did not explain reached-stage checkbox semantics")

            second = task_payload("IN_PROGRESS", ["src/a.txt"], "TASK-2")
            run([py, str(scripts / "update_task_state.py"), "--project-root", str(checklist), "--input", str(write(checklist / "second.json", second))])
            checklist_task_2 = checklist_dir / "task-checklist-TASK-2.md"
            if not checklist_task_2.is_file():
                raise AssertionError("second task did not receive its own checklist")
            task_1_after_task_2 = checklist_task_1.read_text(encoding="utf-8")
            task_2_text = checklist_task_2.read_text(encoding="utf-8")
            if "`TASK-2`" in task_1_after_task_2 or "`TASK-1`" in task_2_text:
                raise AssertionError("task checklist files mixed task context")
            if "Task status: `COMPLETED`" not in task_1_after_task_2 or "Task status: `IN_PROGRESS`" not in task_2_text:
                raise AssertionError("task checklist files did not preserve independent status")
            passed.append("task_specific_progress_checklist_contract")

            cleanup_project = root / "worktree-cleanup-record"
            setup_controlled_git_task(py, scripts, cleanup_project)
            cleanup_complete = task_payload("COMPLETED", ["src/a.txt"])
            cleanup_complete["risk_flags"] = ["security_sensitive"]
            run(
                [
                    py,
                    str(scripts / "update_task_state.py"),
                    "--project-root",
                    str(cleanup_project),
                    "--input",
                    str(write(cleanup_project / "cleanup-complete.json", cleanup_complete)),
                ]
            )
            run(
                [
                    py,
                    str(scripts / "cleanup_worktree.py"),
                    "--project-root",
                    str(cleanup_project),
                    "--task-id",
                    "TASK-1",
                    "--approval-reference",
                    "contract-approval",
                    "--outcome",
                    "KEPT",
                    "--summary",
                    "worktree retained for review",
                ]
            )
            cleanup_artifact = cleanup_project / ".phongka" / "artifacts" / "TASK-1" / "worktree-cleanup.json"
            if not cleanup_artifact.is_file():
                raise AssertionError("cleanup decision was not recorded")
            cleanup_identity = json.loads((cleanup_project / ".phongka" / "state.json").read_text(encoding="utf-8"))["worktree_identity"]
            worktree_dir = cleanup_project / cleanup_identity["path"]
            if not worktree_dir.is_dir():
                raise AssertionError("cleanup_worktree must not remove the worktree itself")
            passed.append("worktree_cleanup_record_only")

            delivery_blocked = root / "worktree-delivery-blocked"
            setup_controlled_git_task(py, scripts, delivery_blocked)
            delivery_blocked_ws = workspace(py, scripts, delivery_blocked, ["src/a.txt"])
            run([py, str(scripts / "record_verification_evidence.py"), "--project-root", str(delivery_blocked), "--input", str(write(delivery_blocked / "verify.json", verification(delivery_blocked_ws)))])
            delivery_complete = task_payload("COMPLETED", ["src/a.txt"])
            delivery_complete["risk_flags"] = ["security_sensitive"]
            run([py, str(scripts / "update_task_state.py"), "--project-root", str(delivery_blocked), "--input", str(write(delivery_blocked / "complete.json", delivery_complete))])
            run([py, str(scripts / "verify_completion_claim.py"), "--project-root", str(delivery_blocked), "--input", str(write(delivery_blocked / "claim.json", claim(["A1", "A2"])))])
            blocked_delivery = {
                "schema_version": 4,
                "task_ids": ["TASK-1"],
                "action": "keep_local",
                "outcome": "KEEP_LOCAL",
                "summary": "deliver",
                "approval_reference": "contract-approval",
                "cleanup": "KEEP",
            }
            run([py, str(scripts / "finalize_delivery.py"), "--project-root", str(delivery_blocked), "--input", str(write(delivery_blocked / "delivery.json", blocked_delivery))], expect=1)
            passed.append("delivery_blocked_without_worktree_cleanup")

    except (AssertionError, OSError, ValueError, KeyError, json.JSONDecodeError) as exc:
        print(json.dumps({"status": "FAILED", "passed": passed, "error": str(exc)}, indent=2))
        return 1
    print(json.dumps({"status": "PASSED", "cases": len(passed), "tests": passed}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
