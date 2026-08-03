"""Validate task-state transitions for executor and reviewer actions."""

from __future__ import annotations

import argparse
import sys

from state_machine import transition_map


EXECUTOR_ALLOWED = transition_map("executor")
REVIEWER_ALLOWED = transition_map("reviewer")


def is_allowed_transition(current: str, next_state: str, *, actor: str = "executor") -> bool:
    current = current.upper()
    next_state = next_state.upper()
    if actor.lower() == "reviewer":
        return next_state in REVIEWER_ALLOWED.get(current, set())
    return next_state in EXECUTOR_ALLOWED.get(current, set())


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--current", required=True)
    parser.add_argument("--next", required=True)
    parser.add_argument("--actor", choices=("executor", "reviewer"), default="executor")
    args = parser.parse_args()
    current = args.current.upper()
    next_state = args.next.upper()
    if not is_allowed_transition(current, next_state, actor=args.actor):
        print(f"INVALID_TRANSITION: {current} -> {next_state} for {args.actor}", file=sys.stderr)
        return 1
    print(f"VALID_TRANSITION: {current} -> {next_state} for {args.actor}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
