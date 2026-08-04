# Packaging Contract

Policy status: ENFORCED (enforced by `skills/agentic-state-tools/scripts/package_skill.py`)

Build a release archive with:

```text
python scripts/package_skill.py --root <package-root> --output <release.zip>
```

The package is allowlist-driven from `MANIFEST.txt`. Only listed files under
the supported skill and test/documentation roots are eligible. Generated
runtime state, caches, bytecode, temporary files, secrets, and unlisted files
are rejected. Content scanning runs before archive creation, and the archive is
reopened and checked against the same member set.

The exact allowlist is:

- Top level: `MANIFEST.txt`, `run_tests.py`, and `README.md` when present.
- `docs/`: `.md`, `.json`, `.txt`, `.yaml`, and `.yml` files.
- `tests/`: `.py`, `.json`, `.yaml`, `.yml`, `.md`, and `.txt` files.
- Each `skills/<skill>/`: `SKILL.md`, `README.md`, `MANIFEST.txt`, and files
  beneath `config/`, `configuration/`, `examples/`, `references/`, `refs/`,
  `schemas/`, or `scripts/`.

Skill-local `tests/` directories are excluded. The package also rejects
`.agent`, `.git`, cache, bytecode, build, coverage, distribution, runtime,
temporary, environment, credential, secret, certificate, key, and log paths,
including `deployment.test.json`, before reading the manifest members.

Packaging is deterministic and local. Publishing to a remote registry is
NOT_IMPLEMENTED; release readiness requires the local package command and its
release inspection tests.
