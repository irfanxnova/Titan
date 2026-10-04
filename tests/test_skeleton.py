"""Verification tests for the Titan foundational skeleton."""

from __future__ import annotations

import io
import json
import os
import sys
import unittest
from dataclasses import FrozenInstanceError
from pathlib import Path
from unittest.mock import patch

# Ensure src/ is on sys.path for direct invocation
_src_path = str(Path(__file__).resolve().parent.parent / "src")
if _src_path not in sys.path:
    sys.path.insert(0, _src_path)

from titan import __version__
from titan.cli import main
from titan.config import TitanConfig


class TestTitanSkeleton(unittest.TestCase):
    """Test suite verifying skeleton setup, configuration, and CLI functionality."""

    def test_version_defined(self) -> None:
        """Verify that the package version string is present and valid."""
        self.assertIsInstance(__version__, str)
        self.assertEqual(__version__, "0.1.0")

    def test_config_defaults(self) -> None:
        """Verify default configuration values."""
        config = TitanConfig()
        self.assertEqual(config.environment, "development")
        self.assertEqual(config.log_level, "INFO")

    def test_config_immutability(self) -> None:
        """Verify that TitanConfig instances cannot be mutated at runtime."""
        config = TitanConfig()
        with self.assertRaises(FrozenInstanceError):
            config.environment = "production"  # type: ignore[misc]

    def test_config_from_env(self) -> None:
        """Verify environment variable overrides for configuration."""
        env_vars = {
            "TITAN_ENV": "experiment-test",
            "TITAN_LOG_LEVEL": "DEBUG",
        }
        with patch.dict(os.environ, env_vars, clear=False):
            config = TitanConfig.from_env()
            self.assertEqual(config.environment, "experiment-test")
            self.assertEqual(config.log_level, "DEBUG")

    def test_cli_help(self) -> None:
        """Verify that the CLI prints help and exits with status code 0."""
        stdout_capture = io.StringIO()
        with patch("sys.stdout", stdout_capture):
            exit_code = main(["--help"])
        self.assertEqual(exit_code, 0)
        self.assertIn("Titan: Experimental distributed-systems research platform", stdout_capture.getvalue())

    def test_cli_status_text(self) -> None:
        """Verify the human-readable status subcommand output."""
        stdout_capture = io.StringIO()
        with patch("sys.stdout", stdout_capture):
            exit_code = main(["status"])
        self.assertEqual(exit_code, 0)
        output = stdout_capture.getvalue()
        self.assertIn("Titan Research Platform", output)
        self.assertIn("0.1.0", output)
        self.assertIn("Milestone:   6 (Replay Fidelity & Divergence Detection)", output)

    def test_cli_status_json(self) -> None:
        """Verify the machine-readable JSON status subcommand output."""
        stdout_capture = io.StringIO()
        with patch("sys.stdout", stdout_capture):
            exit_code = main(["status", "--json"])
        self.assertEqual(exit_code, 0)
        data = json.loads(stdout_capture.getvalue())
        self.assertEqual(data["name"], "Titan")
        self.assertEqual(data["version"], "0.1.0")
        self.assertEqual(data["status"], "ready")

    def test_cli_run_text(self) -> None:
        """Verify the CLI run command executes and displays text report."""
        stdout_capture = io.StringIO()
        with patch("sys.stdout", stdout_capture):
            exit_code = main(["run", "--workers", "1", "--jobs", "2", "--work-units", "50"])
        self.assertEqual(exit_code, 0)
        output = stdout_capture.getvalue()
        self.assertIn("Titan Runtime Execution & Recovery Report", output)
        self.assertIn("Jobs Submitted (Unique):       2", output)
        self.assertIn("Jobs Completed (Unique):       2", output)

    def test_cli_run_json(self) -> None:
        """Verify the CLI run command outputs structured JSON metrics."""
        stdout_capture = io.StringIO()
        with patch("sys.stdout", stdout_capture):
            exit_code = main(["run", "--workers", "1", "--jobs", "3", "--work-units", "50", "--json"])
        self.assertEqual(exit_code, 0)
        data = json.loads(stdout_capture.getvalue())
        self.assertIn("config", data)
        self.assertIn("metrics", data)
        self.assertEqual(data["config"]["workers"], 1)
        self.assertEqual(data["config"]["jobs"], 3)
        self.assertEqual(data["metrics"]["total_unique_submitted"], 3)
        self.assertEqual(data["metrics"]["total_completed_unique"], 3)

    def test_cli_run_invalid_worker_count(self) -> None:
        """Verify the CLI run command rejects non-positive worker count."""
        stderr_capture = io.StringIO()
        with patch("sys.stderr", stderr_capture):
            exit_code = main(["run", "--workers", "0"])
        self.assertEqual(exit_code, 1)
        self.assertIn("Error: --workers must be at least 1", stderr_capture.getvalue())

    def test_cli_run_kill_after_jobs_without_kill_worker(self) -> None:
        """Verify the CLI run command rejects --kill-after-jobs without --kill-worker."""
        stderr_capture = io.StringIO()
        with patch("sys.stderr", stderr_capture):
            exit_code = main(["run", "--kill-after-jobs", "5"])
        self.assertEqual(exit_code, 1)
        self.assertIn("Error: --kill-after-jobs requires --kill-worker to be specified", stderr_capture.getvalue())

    def test_cli_run_failure_injection_via_cli(self) -> None:
        """Verify that failure injection works end-to-end through CLI flags."""
        stdout_capture = io.StringIO()
        with patch("sys.stdout", stdout_capture):
            exit_code = main([
                "run",
                "--workers", "2",
                "--jobs", "10",
                "--work-units", "500",
                "--kill-worker", "0",
                "--kill-after-jobs", "2",
                "--json",
            ])
        self.assertEqual(exit_code, 0)
        data = json.loads(stdout_capture.getvalue())
        self.assertGreaterEqual(data["metrics"]["worker_failures"], 1)
        self.assertGreaterEqual(data["metrics"]["jobs_recovered"], 1)
        self.assertEqual(data["metrics"]["total_completed_unique"], 10)


if __name__ == "__main__":
    unittest.main()
