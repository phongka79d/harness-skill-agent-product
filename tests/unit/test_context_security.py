from __future__ import annotations

import json
import sys
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
SCRIPTS = ROOT / "skills" / "agentic-state-tools" / "scripts"
sys.path.insert(0, str(SCRIPTS))

from redaction import (
    SECRET_CATEGORIES,
    redact_value,
    redaction_report,
    sanitize_for_persistence,
    scan_value,
)  # noqa: E402
from secret_scanner import context_security_errors  # noqa: E402


class ContextSecurityTests(unittest.TestCase):
    def test_scanner_detects_named_secret_categories_without_returning_values(self) -> None:
        private_key = (
            "-----BEGIN " + "RSA PRIVATE KEY-----\nPRIVATE-MATERIAL\n-----END "
            + "RSA PRIVATE KEY-----"
        )
        jwt = "eyJ" + "hbGciOiJIUzI1NiJ9.eyJzdWIiOiIxMjMifQ.signature-value"
        cookie = "Cook" + "ie: session=COOKIE-MATERIAL"
        credentialed_url = "https://user:" + "PASSWORD-MATERIAL@example.test/path"
        database_url = "postgres" + "ql://dbuser:DB-PASSWORD@example.test/app"
        token_assignment = "api_" + "token = TOKEN-MATERIAL"
        secrets = {
            "private": private_key,
            "jwt": jwt,
            "cookie": cookie,
            "url": credentialed_url,
            "database": database_url,
            "base64": "base64=" + "QUJDREVGR0hJSktMTU5PUFFSU1RVVldYWVo=" * 3,
            "token": token_assignment,
        }
        findings = scan_value({"nested": secrets, "markdown": "```\n" + secrets["token"] + "\n```"})
        categories = {item["category"] for item in findings}
        self.assertTrue(SECRET_CATEGORIES.issubset(categories), categories)
        serialized_findings = json.dumps(findings, sort_keys=True)
        for secret in secrets.values():
            self.assertNotIn(secret, serialized_findings)
        for item in findings:
            self.assertEqual(set(item), {"path", "category"})
            self.assertTrue(item["path"])

    def test_redaction_replaces_nested_and_serialized_secrets_and_reports_safe_metadata(self) -> None:
        secret = "token-assignment-secret"
        payload = {
            "credentials": {"api_token": secret},
            "log": f"authorization: Bearer {secret}",
            "markdown": f"```json\n{{\"secret\": \"{secret}\"}}\n```",
        }
        redacted = redact_value(payload)
        self.assertNotIn(secret, json.dumps(redacted, sort_keys=True))
        report = redaction_report(payload, action="REDACT")
        self.assertTrue(report)
        self.assertTrue(all(set(item) == {"path", "category", "action"} for item in report))
        self.assertTrue(all(item["action"] == "REDACT" for item in report))
        self.assertNotIn(secret, json.dumps(report, sort_keys=True))

    def test_context_security_errors_retain_legacy_safe_path_and_category_reporting(self) -> None:
        errors = context_security_errors({"nested": {"api_token": "secret-value"}}, max_bytes=4096)
        self.assertTrue(errors)
        self.assertTrue(any("sensitive-key" in error for error in errors), errors)
        self.assertNotIn("secret-value", json.dumps(errors))

    def test_persistence_policy_rejects_or_redacts_without_secret_disclosure(self) -> None:
        secret = "REDACTION-POLICY-SECRET"
        payload = {"nested": [{"authorization": f"Bearer {secret}"}]}

        with self.assertRaisesRegex(ValueError, "token_assignment") as rejected:
            sanitize_for_persistence(payload, mode="REJECT")
        self.assertNotIn(secret, str(rejected.exception))
        self.assertIn("$.nested[0].authorization", str(rejected.exception))

        redacted, report = sanitize_for_persistence(payload, mode="REDACT")
        self.assertNotIn(secret, json.dumps(redacted, sort_keys=True))
        self.assertEqual({"REDACT"}, {item["action"] for item in report})
        self.assertTrue(all(set(item) == {"path", "category", "action"} for item in report))

    def test_schema_descriptors_are_not_misclassified_as_secret_values(self) -> None:
        schema_like = {
            "properties": {
                "authorization": {"type": "boolean"},
                "token": {"type": "string"},
            }
        }
        self.assertEqual(scan_value(schema_like), [])


if __name__ == "__main__":
    unittest.main()
