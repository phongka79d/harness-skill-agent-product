"""Validate the portable skill package layout and subagent prompt contracts."""
from __future__ import annotations

import argparse
import json
import re
from pathlib import Path

RETIRED_SKILLS = {"agentic-dashboard", "agentic-engineering-wiki", "agentic-plan-reviewer", "agentic-task-reviewer", "agentic-batch-reviewer"}

SKILL_NAME_PATTERN = re.compile(r"^[a-z0-9]+(?:-[a-z0-9]+)*$")

REQUIRED_RETURN_FIELDS = [
    "STATUS:", "SUMMARY:", "FILES_READ:", "FILES_CHANGED:", "EVIDENCE:",
    "FINDINGS_OR_IMPLEMENTATION:", "RISKS:", "OPEN_QUESTIONS:", "NEXT_STEP:"
]


def quoted_metadata_value(metadata: str, key: str, errors: list[str]) -> str | None:
    """Read one required quoted scalar without implementing a YAML parser."""
    line = re.search(rf"^\s*{re.escape(key)}:\s*(.+)$", metadata, re.M)
    if not line:
        errors.append(f"primary metadata missing {key}")
        return None
    raw_value = line.group(1).strip()
    if len(raw_value) < 2 or raw_value[0] != '"' or raw_value[-1] != '"':
        errors.append(f"primary metadata {key} must be a quoted string")
        return None
    value = raw_value[1:-1]
    if not value.strip():
        errors.append(f"primary metadata {key} must be non-empty")
        return None
    return value


def primary_entrypoint_guard(root: Path, config: dict, errors: list[str]) -> None:
    """Check the configured primary skill's explicit host entrypoint contract."""
    primary_skill = config.get("subagent_policy", {}).get("primary_skill")
    if not isinstance(primary_skill, str) or not primary_skill:
        errors.append("subagent_policy.primary_skill must name the primary skill")
        return

    skill_dir = root / primary_skill
    skill_file = skill_dir / "SKILL.md"
    if not skill_file.is_file():
        errors.append(f"primary entrypoint skill is missing: {primary_skill}")
        return

    body = skill_file.read_text(encoding="utf-8")
    frontmatter = re.match(r"^---\n(.*?)\n---\n", body, re.M | re.S)
    if not frontmatter:
        errors.append(f"primary entrypoint has no frontmatter: {primary_skill}")
    else:
        header = frontmatter.group(1)
        description = re.search(r"^description:\s*(.+)$", header, re.M)
        description_text = description.group(1).strip() if description else ""
        for marker in (
            f"/{primary_skill}",
            f"${primary_skill}",
            "host slash-skill list",
            "slash picker selection",
            "slash-text",
            "implicit repository work",
            "current active `.phongka` workflow/task",
        ):
            if marker not in description_text:
                errors.append(f"primary frontmatter description missing entrypoint marker: {marker}")

    for marker in (
        f"/{primary_skill}",
        f"${primary_skill}",
        "host slash-skill list",
        "slash picker selection",
        "slash-text",
        "implicit repository work",
        "current active `.phongka` workflow/task",
        "sole Primary Agent",
        "remains Primary through the terminal report",
        "never delegates, spawns, replaces, or hands off the Primary role or final report",
        "classify `task_route`",
        "resolve `execution_depth`",
        "load the returned `required_skills` in order",
        "For each new workflow request",
        "read and continue the existing active task and its workflow decision",
        "must not re-resolve, reinitialize, or rebind",
        "Reroute only when the user clearly replaces the active task",
        "never ask the user to name downstream skills",
    ):
        if marker not in body:
            errors.append(f"primary SKILL.md missing entrypoint contract: {marker}")
    if "On every activation, the receiving Primary automatically:" in body:
        errors.append("primary SKILL.md applies new-workflow routing to every activation")

    metadata_file = skill_dir / "agents/openai.yaml"
    if not metadata_file.is_file():
        errors.append(f"primary metadata is missing: {metadata_file}")
    else:
        metadata = metadata_file.read_text(encoding="utf-8")
        quoted_metadata_value(metadata, "display_name", errors)
        short_description = quoted_metadata_value(metadata, "short_description", errors)
        default_prompt = quoted_metadata_value(metadata, "default_prompt", errors)
        if short_description is not None and not 25 <= len(short_description) <= 64:
            errors.append("primary metadata short_description must be 25-64 characters")
        if default_prompt is not None:
            if f"${primary_skill}" not in default_prompt:
                errors.append(f"primary metadata default_prompt must mention ${primary_skill}")
            if "Primary Agent" not in default_prompt:
                errors.append("primary metadata default_prompt must mention Primary Agent")
            workflow = re.search(r"\bworkflows?\b", default_prompt, re.I)
            action = re.search(
                r"\b(?:run(?:s|ning)?|rout(?:e|es|ing)|resolv(?:e|es|ing)|"
                r"execut(?:e|es|ing)|start(?:s|ing)?|continu(?:e|es|ing)|"
                r"orchestrat(?:e|es|ing))\b",
                default_prompt,
                re.I,
            )
            if workflow is None or action is None:
                errors.append("primary metadata default_prompt must express workflow intent")
        if not re.search(r"^\s*allow_implicit_invocation:\s*true\s*$", metadata, re.M):
            errors.append("primary metadata policy.allow_implicit_invocation must be true")

    host_bootstrap = skill_dir / "references/host-bootstrap.md"
    if not host_bootstrap.is_file():
        errors.append(f"primary host bootstrap reference is missing: {host_bootstrap}")
    else:
        host_text = host_bootstrap.read_text(encoding="utf-8")
        for marker in (
            "Desktop",
            "slash list",
            "$skill-name",
            "/skills",
            "/prompts:<name>",
            "cannot register arbitrary host slash commands",
            "not whole-chat persistence",
            "current active `.phongka` task and workflow decision",
        ):
            if marker not in host_text:
                errors.append(f"primary host bootstrap missing host-truth marker: {marker}")


def frontmatter_name(path: Path) -> str:
    text = path.read_text(encoding="utf-8")
    match = re.match(r"---\n.*?^name:\s*([^\n]+).*?\n---\n", text, re.M | re.S)
    if not match:
        raise ValueError(f"missing valid frontmatter: {path}")
    return match.group(1).strip()


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--skills-root", required=True)
    args = parser.parse_args()
    root = Path(args.skills_root).expanduser().resolve()
    config_path = root / "agentic-configuration/config/agentic-config.json"
    config = json.loads(config_path.read_text(encoding="utf-8"))
    errors: list[str] = []
    primary_entrypoint_guard(root, config, errors)
    present = {p.name for p in root.iterdir() if p.is_dir()}
    for retired in sorted(RETIRED_SKILLS & present):
        errors.append(f"retired skill still present: {retired}")
    for skill_dir in sorted(p for p in root.iterdir() if p.is_dir()):
        skill = skill_dir / "SKILL.md"
        if not skill.is_file():
            errors.append(f"missing SKILL.md: {skill_dir.name}")
            continue
        try:
            declared_name = frontmatter_name(skill)
            if declared_name != skill_dir.name:
                errors.append(f"frontmatter name mismatch: {skill_dir.name}")
            if len(declared_name) > 64 or SKILL_NAME_PATTERN.fullmatch(declared_name) is None:
                errors.append(f"invalid skill name: {declared_name}")
            body = skill.read_text(encoding="utf-8")
            description = re.search(r"^description:\s*(.+)$", body, re.M)
            if not description or not description.group(1).strip().lower().startswith("use"):
                errors.append(f"description must start with Use: {skill_dir.name}")
            elif len(description.group(1).strip()) > 1024:
                errors.append(f"description exceeds 1024 characters: {skill_dir.name}")
            if body.count("\n") + 1 > 500:
                errors.append(f"SKILL.md exceeds 500 lines: {skill_dir.name}")
        except ValueError as exc:
            errors.append(str(exc))
    envelope = root / "agentic-engineering-core/prompts/subagent-envelope.md"
    if not envelope.is_file():
        errors.append("missing shared subagent envelope")
    else:
        body = envelope.read_text(encoding="utf-8")
        for field in REQUIRED_RETURN_FIELDS:
            if field not in body:
                errors.append(f"subagent envelope missing {field}")
        if "{{ROLE_MODE}}" not in body:
            errors.append("subagent envelope missing ROLE_MODE")
        if "REPAIR_REQUIRED" not in body or "ISSUES_FOUND" in body:
            errors.append("subagent envelope status contract is inconsistent")
    if "context" in config["skill_routing"]["role_skills"]:
        errors.append("retired context-builder route is still configured")
    for agent_id, record in config["agents"].items():
        if record.get("dispatch_kind") != "model":
            continue
        prompt = root / record.get("prompt_path", "")
        skill_name = record.get("skill")
        skill_file = root / str(skill_name) / "SKILL.md"
        if not isinstance(skill_name, str) or not skill_file.is_file():
            errors.append(f"{agent_id}: model skill is missing: {skill_name}")
        else:
            skill_body = skill_file.read_text(encoding="utf-8")
            description = re.search(r"^description:\s*(.+)$", skill_body, re.M)
            expected_prefix = "Use only when dispatched by agentic-engineering-core"
            if not description or not description.group(1).strip().startswith(expected_prefix):
                errors.append(f"{agent_id}: model-role description must be dispatch-only")
        if not prompt.is_file():
            errors.append(f"{agent_id}: missing prompt {record.get('prompt_path')}")
        else:
            try:
                prompt_owner = prompt.relative_to(root).parts[0]
                if prompt_owner != skill_name:
                    errors.append(f"{agent_id}: prompt is outside owning skill")
            except ValueError:
                errors.append(f"{agent_id}: prompt escapes skills root")
            prompt_body = prompt.read_text(encoding="utf-8")
            if "Use after the shared subagent envelope" not in prompt_body:
                errors.append(f"{agent_id}: prompt does not declare shared envelope")
            if agent_id == "agent-independent-reviewer":
                for mode in ("## Mode: plan", "## Mode: task", "## Mode: integration"):
                    if mode not in prompt_body:
                        errors.append(f"{agent_id}: missing reviewer contract {mode}")
        if record.get("fresh_context") is not True:
            errors.append(f"{agent_id}: fresh_context must be true")
    routed_skills = set(config["skill_routing"]["process_skills"].values()) | set(config["skill_routing"]["role_skills"].values())
    missing_routed = sorted(skill for skill in routed_skills if not (root / skill / "SKILL.md").is_file())
    for skill in missing_routed:
        errors.append(f"routed skill missing: {skill}")
    model_skills = {record.get("skill") for record in config["agents"].values() if record.get("dispatch_kind") == "model"}
    for stage in config["subagent_policy"]["dispatchable_stages"]:
        skill_name = config["skill_routing"]["process_skills"].get(stage) or config["skill_routing"]["role_skills"].get(stage)
        if skill_name not in model_skills:
            errors.append(f"dispatchable stage lacks model agent: {stage}")
    if errors:
        print(json.dumps({"status":"INVALID","errors":errors}, indent=2))
        return 1
    print(json.dumps({"status":"VALID","skills":len([p for p in root.iterdir() if p.is_dir()]),"model_agents":sum(1 for x in config['agents'].values() if x.get('dispatch_kind') == 'model')}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
