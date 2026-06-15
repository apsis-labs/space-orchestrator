"""Tests for the CLI."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from orchestrator.cli import main


class TestCLI:
    """CLI smoke tests."""

    def test_no_command_shows_help(self, capsys: pytest.CaptureFixture[str]) -> None:
        """Running with no command should show help."""
        result = main([])
        assert result == 0
        captured = capsys.readouterr()
        assert "orchestrator" in captured.out
        assert "passes" in captured.out

    def test_passes_with_bundled_data(self, capsys: pytest.CaptureFixture[str]) -> None:
        """passes command should work with bundled TLE and stations."""
        result = main(["passes", "--hours", "6"])
        assert result == 0
        captured = capsys.readouterr()
        assert "Computing passes" in captured.out

    def test_passes_output_json(self, tmp_path: Path) -> None:
        """passes command should output valid JSON."""
        output = tmp_path / "passes.json"
        result = main(["passes", "--hours", "6", "--output", str(output)])
        assert result == 0
        assert output.exists()

        data = json.loads(output.read_text())
        assert isinstance(data, list)

    def test_schedule_with_bundled_data(self, capsys: pytest.CaptureFixture[str]) -> None:
        """schedule command should work with bundled data."""
        result = main(["schedule", "--hours", "6"])
        assert result == 0
        captured = capsys.readouterr()
        assert "Scheduled:" in captured.out

    def test_schedule_output_json(self, tmp_path: Path) -> None:
        """schedule command should output valid JSON."""
        output = tmp_path / "plan.json"
        result = main(["schedule", "--hours", "6", "--output", str(output)])
        assert result == 0
        assert output.exists()

        data = json.loads(output.read_text())
        assert "scheduled" in data
        assert "dropped" in data

    def test_reconcile_with_no_failures(self, capsys: pytest.CaptureFixture[str]) -> None:
        """reconcile should work with 0% failure rate."""
        result = main(["reconcile", "--hours", "6", "--failure-rate", "0"])
        # May return 0 even if no contacts (geometry dependent)
        assert result == 0

    def test_reconcile_with_failures(
        self, capsys: pytest.CaptureFixture[str], tmp_path: Path
    ) -> None:
        """reconcile should handle failures and save report."""
        output = tmp_path / "report.json"
        result = main([
            "reconcile",
            "--hours", "12",
            "--failure-rate", "0.3",
            "--seed", "42",
            "--output", str(output),
        ])
        assert result == 0

        captured = capsys.readouterr()
        assert "Results:" in captured.out or "No contacts scheduled" in captured.out

    def test_dashboard_requires_report(self) -> None:
        """dashboard should fail without --report."""
        with pytest.raises(SystemExit):
            main(["dashboard"])

    def test_dashboard_missing_report_file(self, tmp_path: Path) -> None:
        """dashboard should error on missing report file."""
        result = main(["dashboard", "--report", str(tmp_path / "missing.json")])
        assert result == 1

    def test_full_workflow(self, tmp_path: Path) -> None:
        """Test the full workflow: schedule -> reconcile -> dashboard."""
        report_path = tmp_path / "report.json"
        dashboard_path = tmp_path / "dashboard.html"

        # Run reconcile to get a report
        result = main([
            "reconcile",
            "--hours", "6",
            "--failure-rate", "0.1",
            "--output", str(report_path),
        ])

        # If no contacts were scheduled, skip the rest
        if not report_path.exists():
            pytest.skip("No contacts scheduled (geometry dependent)")

        # Generate dashboard
        result = main([
            "dashboard",
            "--report", str(report_path),
            "--output", str(dashboard_path),
        ])
        assert result == 0
        assert dashboard_path.exists()

        html = dashboard_path.read_text()
        assert "<!doctype html>" in html.lower()
