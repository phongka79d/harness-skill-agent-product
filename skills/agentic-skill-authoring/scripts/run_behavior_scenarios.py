"""Validate and evaluate provider-neutral skill pressure scenarios."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import sys
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "agentic-state-tools" / "scripts"))
from validate_payload import validate


SCHEMA_PATH = Path(__file__).resolve().parents[1] / "schemas" / "behavior-scenario.schema.json"
STATUSES = {"PASS", "FAIL", "BLOCKED", "INCONCLUSIVE"}


class ScenarioError(ValueError):
    """A scenario or observation is malformed."""


def _timestamp() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def _load_value(path: str | Path) -> Any:
    target = Path(path).expanduser().resolve()
    try:
        text = target.read_text(encoding="utf-8")
    except OSError as exc:
        raise ScenarioError(f"unable to read {target}: {exc}") from exc
    try:
        if target.suffix.lower() == ".json":
            return json.loads(text)
        try:
            import yaml  # type: ignore
        except ImportError as exc:
            raise ScenarioError("YAML scenarios require PyYAML or a JSON scenario file") from exc
        return yaml.safe_load(text)
    except (TypeError, ValueError, json.JSONDecodeError) as exc:
        raise ScenarioError(f"invalid scenario document {target}: {exc}") from exc


def _profile_id(path: str | Path | None) -> str:
    if path is None:
        return "UNSPECIFIED"
    value = _load_value(path)
    if not isinstance(value, dict) or not isinstance(value.get("profile_id"), str) or not value["profile_id"].strip():
        raise ScenarioError("profile document must declare a non-empty profile_id")
    return value["profile_id"]


def _validate_profile(path: str | Path | None, scenario_ids: list[str]) -> str:
    profile_id = _profile_id(path)
    if path is None:
        return profile_id
    value = _load_value(path)
    required = value.get("required_scenarios") if isinstance(value, dict) else None
    if isinstance(required, list) and not set(str(item) for item in required).issubset(set(scenario_ids)):
        raise ScenarioError("profile required_scenarios are missing from the supplied scenario set")
    return profile_id


def _config_hash(config: str) -> str:
    candidate = Path(config).expanduser()
    material = candidate.read_bytes() if candidate.is_file() else config.encode("utf-8")
    return hashlib.sha256(material).hexdigest()


def _schema() -> dict[str, Any]:
    try:
        return json.loads(SCHEMA_PATH.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise ScenarioError(f"behavior scenario schema is unreadable: {exc}") from exc


def validate_scenario(value: Any) -> None:
    errors = validate(value, _schema(), base_path=SCHEMA_PATH.parent)
    if errors:
        raise ScenarioError("behavior scenario violates its schema: " + "; ".join(errors))


def _normalize_pressure_scenario(value: dict[str, Any], suite_id: str) -> dict[str, Any]:
    expected = value["expected"]
    evidence = expected["evidence"]
    return {
        "schema_version": 1,
        "scenario_id": value["id"],
        "title": value["name"],
        "owning_skill": "agentic-skill-authoring",
        "pressure": {
            "type": value["pressure"],
            "rationalization": value["prompt"],
            "ambiguity": value["prompt"],
            "risk": ", ".join(value["forbidden"]),
        },
        "prompt": value["prompt"],
        "expected_behaviors": [expected["agent_action"]],
        "forbidden_behaviors": list(value["forbidden"]),
        "required_evidence": list(evidence),
        "expected_result": expected["scenario_result"],
        "rationalizations": [value["prompt"]],
        "profile_guidance": {
            "low_risk": "Use the profile's focused evidence without removing the safety behavior.",
            "strict": "Record every declared evidence item and the current workspace/config identity.",
        },
        "assertions": [
            {
                "assertion_id": item,
                "description": f"Evidence item required by {suite_id}: {item}",
                "expected": "OBSERVED",
            }
            for item in evidence
        ],
    }


def _scenario_items(value: dict[str, Any]) -> tuple[bool, list[dict[str, Any]]]:
    if isinstance(value.get("scenarios"), list):
        scenarios = value["scenarios"]
        if not all(isinstance(item, dict) for item in scenarios):
            raise ScenarioError("scenario suite entries must be objects")
        if "scenario_set_id" in value:
            return True, [_normalize_pressure_scenario(item, value["scenario_set_id"]) for item in scenarios]
        return True, scenarios
    return False, [value]


def _observation_for(observation: Any, scenario_id: str) -> dict[str, Any] | None:
    if observation is None:
        return None
    if isinstance(observation, dict) and isinstance(observation.get("results"), list):
        candidates = observation["results"]
    elif isinstance(observation, list):
        candidates = observation
    else:
        candidates = [observation]
    for item in candidates:
        if isinstance(item, dict) and item.get("scenario_id", scenario_id) == scenario_id:
            return item
    return None


def _assertion_status(scenario: dict[str, Any], observation: dict[str, Any]) -> str:
    declared = observation.get("status", observation.get("result"))
    if isinstance(declared, str) and declared.upper() in {"BLOCKED", "FAIL", "INCONCLUSIVE"}:
        return declared.upper()
    if observation.get("blocked") is True:
        return "BLOCKED"
    actual = observation.get("assertions")
    if not isinstance(actual, dict):
        return "INCONCLUSIVE"
    missing = False
    failed = False
    for assertion in scenario["assertions"]:
        assertion_id = assertion["assertion_id"]
        if assertion_id not in actual:
            missing = True
            continue
        value = actual[assertion_id]
        expected = assertion["expected"]
        if expected == "OBSERVED":
            matches = value is True or str(value).upper() in {"OBSERVED", "PRESENT", "PASS", "TRUE"}
        elif expected == "ABSENT":
            matches = value is False or str(value).upper() in {"ABSENT", "NOT_OBSERVED", "FALSE", "PASS"}
        else:
            matches = value is True or str(value).upper() in {"PRESENT", "OBSERVED", "PASS", "TRUE"}
        if not matches:
            failed = True
    if failed:
        return "FAIL"
    if missing:
        return "INCONCLUSIVE"
    return "PASS"


def _missing_required_evidence(scenario: dict[str, Any], evidence: list[Any]) -> list[str]:
    """Return declared evidence items that the observation did not record."""

    observed = {str(item).strip() for item in evidence if str(item).strip()}
    return [
        str(item)
        for item in scenario.get("required_evidence", [])
        if str(item).strip() not in observed
    ]


def evaluate_observation(
    scenario: dict[str, Any],
    observation: dict[str, Any] | None = None,
    *,
    model: str = "UNSPECIFIED",
    config: str = "UNSPECIFIED",
    profile_id: str = "UNSPECIFIED",
) -> dict[str, Any]:
    """Produce a deterministic, model/config-bound result for one scenario."""

    if not isinstance(model, str) or not model.strip() or not isinstance(config, str) or not config.strip():
        raise ScenarioError("model and config must be non-empty strings")
    raw = observation or {}
    status = "INCONCLUSIVE" if observation is None else _assertion_status(scenario, raw)
    evidence = raw.get("evidence", []) if isinstance(raw.get("evidence", []), list) else []
    rationalizations = raw.get("rationalizations", []) if isinstance(raw.get("rationalizations", []), list) else []
    if status == "PASS" and not evidence:
        status = "INCONCLUSIVE"
    missing_evidence = _missing_required_evidence(scenario, evidence)
    if status == "PASS" and missing_evidence:
        status = "INCONCLUSIVE"
    expected_result = scenario.get("expected_result", "INCONCLUSIVE")
    expectation_met = status == expected_result
    notes = str(raw.get("notes", ""))
    if missing_evidence:
        evidence_note = "missing required evidence: " + ", ".join(missing_evidence)
        notes = f"{notes}; {evidence_note}" if notes else evidence_note
    if not expectation_met:
        expectation_note = f"actual result {status} does not match expected result {expected_result}"
        notes = f"{notes}; {expectation_note}" if notes else expectation_note
    result = {
        "scenario_id": scenario["scenario_id"],
        "status": status,
        "result": status,
        "expected_result": expected_result,
        "expectation_met": expectation_met,
        "model": model,
        "config": config,
        "profile_id": profile_id,
        "model_ref": str(raw.get("model_ref", model)),
        "deployment_ref": str(raw.get("deployment_ref", config)),
        "config_hash": (
            str(raw["config_hash"]).lower()
            if isinstance(raw.get("config_hash"), str) and re.fullmatch(r"[0-9a-fA-F]{64}", raw["config_hash"])
            else _config_hash(config)
        ),
        "evaluated_at": _timestamp(),
        "observed_behaviors": raw.get("observed_behaviors", []) if isinstance(raw.get("observed_behaviors", []), list) else [],
        "rationalizations": [str(item) for item in rationalizations],
        "evidence": [str(item) for item in evidence],
        "assertions": raw.get("assertions", {}) if isinstance(raw.get("assertions", {}), dict) else {},
        "notes": notes,
    }
    if profile_id != "UNSPECIFIED" and status == "PASS" and not (
        isinstance(raw.get("evidence_location"), str) and raw["evidence_location"].strip()
    ):
        result["status"] = "INCONCLUSIVE"
        result["result"] = "INCONCLUSIVE"
    if isinstance(raw.get("evidence_location"), str) and raw["evidence_location"].strip():
        result["evidence_location"] = raw["evidence_location"]
    if isinstance(raw.get("exit_code"), int) and not isinstance(raw["exit_code"], bool) and raw["exit_code"] >= 0:
        result["exit_code"] = raw["exit_code"]
    return result


def run_behavior_scenarios(
    scenario: str | Path,
    observation: str | Path | None = None,
    *,
    model: str = "UNSPECIFIED",
    config: str = "UNSPECIFIED",
    profile_id: str = "UNSPECIFIED",
) -> dict[str, Any]:
    """Validate one scenario document and return its execution result(s)."""

    payload = _load_value(scenario)
    if not isinstance(payload, dict):
        raise ScenarioError("scenario document must be an object")
    validate_scenario(payload)
    is_suite, scenarios = _scenario_items(payload)
    raw_observation = _load_value(observation) if observation is not None else None
    results = [
        evaluate_observation(
            item,
            _observation_for(raw_observation, item["scenario_id"]),
            model=model,
            config=config,
            profile_id=profile_id,
        )
        for item in scenarios
    ]
    if not is_suite:
        return {**scenarios[0], "execution": results[0]}
    return {
        "schema_version": payload["schema_version"],
        "suite_id": payload.get("suite_id", payload.get("scenario_set_id", "scenario-suite")),
        "scenarios": scenarios,
        "model": model,
        "config": config,
        "profile_id": profile_id,
        "evaluated_at": _timestamp(),
        "execution_results": results,
    }


def _write_json(path: str | Path, value: dict[str, Any]) -> None:
    target = Path(path).expanduser().resolve()
    target.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary = tempfile.mkstemp(prefix=f".{target.name}.", suffix=".tmp", dir=target.parent)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8", newline="\n") as handle:
            json.dump(value, handle, ensure_ascii=False, indent=2, sort_keys=True)
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, target)
    except Exception:
        try:
            os.unlink(temporary)
        except FileNotFoundError:
            pass
        raise


def _expectations_satisfied(result: dict[str, Any]) -> bool:
    execution = result.get("execution")
    if isinstance(execution, dict):
        return execution.get("expectation_met") is True
    executions = result.get("execution_results")
    return isinstance(executions, list) and bool(executions) and all(
        isinstance(item, dict) and item.get("expectation_met") is True for item in executions
    )


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    source = parser.add_mutually_exclusive_group(required=True)
    source.add_argument("--scenario", "--input", dest="scenario")
    source.add_argument("--scenario-root")
    parser.add_argument("--observation")
    parser.add_argument("--model", default="UNSPECIFIED")
    parser.add_argument("--config", default="UNSPECIFIED")
    parser.add_argument("--profile")
    parser.add_argument("--output")
    parser.add_argument("--validate-only", action="store_true")
    args = parser.parse_args()
    try:
        profile_id = _profile_id(args.profile)
        if args.scenario_root:
            root = Path(args.scenario_root).expanduser().resolve()
            files = sorted(path for path in root.iterdir() if path.suffix.lower() in {".yaml", ".yml", ".json"})
            if not files:
                raise ScenarioError("scenario root contains no YAML or JSON scenarios")
            documents = [_load_value(path) for path in files]
            scenarios: list[dict[str, Any]] = []
            for document in documents:
                if isinstance(document, dict) and "scenario_id" not in document and "scenarios" not in document and (
                    "profile_id" in document or document.get("kind") == "profile"
                ):
                    continue
                validate_scenario(document)
                _, items = _scenario_items(document)
                scenarios.extend(items)
            payload = {"schema_version": 1, "suite_id": root.name, "scenarios": scenarios}
            validate_scenario(payload)
            profile_id = _validate_profile(args.profile, [item["scenario_id"] for item in scenarios])
            if args.validate_only:
                print("SCENARIOS_VALID")
                return 0
            observation = _load_value(args.observation) if args.observation else None
            result = {
                "schema_version": 1,
                "suite_id": root.name,
                "scenarios": scenarios,
                "model": args.model,
                "config": args.config,
                "profile_id": profile_id,
                "evaluated_at": _timestamp(),
                "execution_results": [
                    evaluate_observation(
                        item,
                        _observation_for(observation, item["scenario_id"]),
                        model=args.model,
                        config=args.config,
                        profile_id=profile_id,
                    )
                    for item in scenarios
                ],
            }
        else:
            payload = _load_value(args.scenario)
            validate_scenario(payload)
            _, scenario_items = _scenario_items(payload)
            profile_id = _validate_profile(args.profile, [item["scenario_id"] for item in scenario_items])
            if args.validate_only:
                print("SCENARIO_VALID")
                return 0
            result = run_behavior_scenarios(
                args.scenario,
                args.observation,
                model=args.model,
                config=args.config,
                profile_id=profile_id,
            )
        validate_scenario(result)
        if args.output:
            _write_json(args.output, result)
    except (OSError, TypeError, ValueError, json.JSONDecodeError, ScenarioError) as exc:
        print(f"SCENARIO_REJECTED: {exc}")
        return 1
    print(json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True))
    return 0 if _expectations_satisfied(result) else 1


if __name__ == "__main__":
    raise SystemExit(main())
