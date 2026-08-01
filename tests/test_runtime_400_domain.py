from __future__ import annotations

import unittest

from plugins.xiaoh.xiaoh_runtime.domain.models import (
    ActivationState,
    DiagnosticResult,
    DiagnosticStatus,
    DoctorReport,
    InstallationTransaction,
    TransactionPhase,
)


class Runtime400DomainTests(unittest.TestCase):
    def test_doctor_aggregates_mixed_diagnostics_without_losing_results(self) -> None:
        diagnostics = [
            DiagnosticResult("plugin", DiagnosticStatus.PASSED, facts={"version": "4.0.0"}),
            DiagnosticResult(
                "vault",
                DiagnosticStatus.DEGRADED,
                warnings=["customized template"],
                remediation=["review the preserved customization"],
            ),
            DiagnosticResult(
                "hook-runtime",
                DiagnosticStatus.SKIPPED,
                skipped_reason="current-process Hook evidence is unavailable",
                runtime_checked=True,
            ),
            DiagnosticResult(
                "validator",
                DiagnosticStatus.FAILED,
                errors=["schema drift"],
            ),
        ]

        report = DoctorReport.from_diagnostics(
            diagnostics,
            installation_status="files_installed",
        ).to_dict()

        self.assertEqual(4, len(report["diagnostics"]))
        self.assertEqual("failed", report["status"])
        self.assertEqual("runtime_unverified", report["activation_state"])
        self.assertIn("schema drift", report["errors"])
        self.assertIn("hook-runtime", report["unresolved_items"])

    def test_runtime_activation_requires_every_required_diagnostic(self) -> None:
        required = (
            "plugin",
            "loaded-skill",
            "managed-runtime",
            "agents",
            "hooks",
            "validator",
            "vault",
            "workspace",
            "automation",
            "playbook",
        )
        diagnostics = [
            DiagnosticResult(name, DiagnosticStatus.PASSED, runtime_checked=True)
            for name in required
        ]

        report = DoctorReport.from_diagnostics(
            diagnostics,
            installation_status="files_installed",
            required_for_activation=required,
        )

        self.assertEqual(ActivationState.VERIFIED, report.activation_state)

    def test_transaction_rejects_illegal_phase_jump(self) -> None:
        transaction = InstallationTransaction.new("setup")
        transaction.advance(TransactionPhase.CANDIDATE_VALIDATED)

        with self.assertRaisesRegex(ValueError, "illegal transaction transition"):
            transaction.advance(TransactionPhase.COMMITTED)

    def test_transaction_records_successful_writes_exactly_once(self) -> None:
        transaction = InstallationTransaction.new("update")
        transaction.advance(TransactionPhase.CANDIDATE_VALIDATED)
        transaction.advance(TransactionPhase.BACKED_UP)
        transaction.advance(TransactionPhase.SWITCHING)
        transaction.record_write(
            target="/isolated/codex/hooks",
            old_digest="old",
            new_digest="new",
            phase=TransactionPhase.SWITCHING,
        )
        transaction.record_write(
            target="/isolated/codex/hooks",
            old_digest="old",
            new_digest="new",
            phase=TransactionPhase.SWITCHING,
        )

        self.assertEqual(["/isolated/codex/hooks"], transaction.actual_writes)
        payload = transaction.to_dict()
        self.assertEqual("xiaoh-install-transaction/v2", payload["schema_version"])
        self.assertEqual("in_progress", payload["result"])
        self.assertEqual(
            ["planned", "candidate_validated", "backed_up", "switching"],
            [item["phase"] for item in payload["phase_history"]],
        )


if __name__ == "__main__":
    unittest.main()
