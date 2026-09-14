#!/usr/bin/env python3
"""Deterministic checks for runner argument and result handling."""

from copy import deepcopy
import json
from pathlib import Path
import signal
import subprocess
from types import SimpleNamespace
import tempfile
import unittest
from unittest.mock import patch

from run_endpoint import endpoint_command
from run_matrix import (
    CASES,
    OWNER_LABEL,
    cleanup_containers,
    main,
    matrix_exit_status,
    merge_results,
    run_case,
    write_report,
)


class RunnerTests(unittest.TestCase):
    def test_client_session_and_ca(self):
        command = endpoint_command(
            {
                "ROLE": "client",
                "TESTCASE": "transfer-unidirectional-receive",
                "REQUESTS": "https://server4:443/wt/file1 https://server4:443/wt/file2",
            }
        )
        self.assertEqual(command[command.index("-U") + 1], "https://server4:443/wt")
        self.assertEqual(command[command.index("-J") + 1], "/certs/ca.pem")

    def test_unsupported_and_malformed_input(self):
        self.assertIsNone(endpoint_command({"ROLE": "server", "TESTCASE": "unknown"}))
        self.assertIsNone(endpoint_command({"ROLE": "client", "TESTCASE": "transfer"}))
        for url in [
            "http://server/wt/file",
            "https://user@server/wt/file",
            "https://server/../file",
            "https://server/wt/file?query=1",
        ]:
            with self.subTest(url=url), self.assertRaises(ValueError):
                endpoint_command(
                    {"ROLE": "client", "TESTCASE": "handshake", "REQUESTS": url}
                )

    def test_merge_official_role_runs(self):
        passed = [{"abbr": "H", "result": "succeeded"}]
        failed = [{"abbr": "H", "result": "failed"}]
        runs = [
            {
                "clients": ["xquic", "peer"],
                "servers": ["xquic"],
                "results": [passed, failed],
            },
            {"clients": ["xquic"], "servers": ["peer"], "results": [passed]},
        ]
        merged = merge_results(runs, ["xquic", "peer"], ["xquic", "peer"])
        self.assertEqual(
            [row[:1] for row in merged["results"][:3]], [passed, passed, failed]
        )
        self.assertIsNone(merged["results"][3][0]["result"])

    def test_merge_single_case_runs_keeps_both_original_outcomes(self):
        runs = [
            {
                "clients": ["peer"],
                "servers": ["xquic"],
                "results": [[{"abbr": abbr, "name": case, "result": state}]],
            }
            for (abbr, case), state in zip(CASES, ("failed", "succeeded"))
        ]
        originals = deepcopy(runs)
        merged = merge_results(runs, ["peer"], ["xquic"])
        self.assertEqual(
            [r["result"] for r in merged["results"][0]], ["failed", "succeeded"]
        )
        self.assertEqual(runs, originals)

    def test_matrix_keeps_direction_failure_and_not_run(self):
        result = {
            "clients": ["peer", "xquic"],
            "servers": ["xquic", "peer"],
            "results": [
                [
                    {"abbr": "H", "result": "failed"},
                    {"abbr": "UR", "result": "unsupported"},
                ],
                [],
                [
                    {"abbr": "H", "result": "succeeded"},
                    {"abbr": "UR", "result": "succeeded"},
                ],
                [{"abbr": "H", "result": None}, {"abbr": "UR", "result": "failed"}],
            ],
        }
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory)
            write_report(
                result, output, {"started_at": "test", "runner_revision": "test"}
            )
            report = (output / "results.md").read_text()
            self.assertIn("| peer | xquic | FAIL | UNSUPPORTED |", report)
            self.assertIn("| xquic | xquic | PASS | PASS |", report)
            self.assertIn("| xquic | peer | NOT RUN | FAIL |", report)
            self.assertNotIn("| peer | peer |", report)

    def test_report_links_only_existing_original_case_results(self):
        result = {"clients": ["xquic"], "servers": ["xquic"], "results": [[]]}
        metadata = {"started_at": "test", "runner_revision": "test"}
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory)
            case_dir = output / "upstream" / "xquic_xquic"
            case_dir.mkdir(parents=True)
            (case_dir / "handshake.json").write_text('{\n  "original": true\n}\n')
            write_report(result, output, metadata)
            report = (output / "results.md").read_text()
            self.assertIn("[H](upstream/xquic_xquic/handshake.json)", report)
            self.assertNotIn("transfer-unidirectional-receive.json", report)
            (case_dir / "transfer-unidirectional-receive.json").write_text("{}")
            write_report(result, output, metadata)
            report = (output / "results.md").read_text()
            self.assertIn(
                "[UR](upstream/xquic_xquic/transfer-unidirectional-receive.json)",
                report,
            )
            self.assertEqual(
                (case_dir / "handshake.json").read_text(), '{\n  "original": true\n}\n'
            )

    def test_matrix_status_requires_all_requested_cases(self):
        passed = [
            {"abbr": "H", "result": "succeeded"},
            {"abbr": "UR", "result": "succeeded"},
        ]
        result = {
            "clients": ["xquic", "peer"],
            "servers": ["xquic", "peer"],
            "results": [passed, passed, passed, []],
        }
        self.assertEqual(matrix_exit_status(result), 0)
        for state in ("failed", "unsupported", None):
            changed = deepcopy(result)
            changed["results"][1][1]["result"] = state
            with self.subTest(state=state):
                self.assertEqual(matrix_exit_status(changed), 1)
        missing = deepcopy(result)
        missing["results"][2].pop()
        self.assertEqual(matrix_exit_status(missing), 1)

    @staticmethod
    def check_output(command, **kwargs):
        if command[:3] == ["docker", "image", "inspect"]:
            return json.dumps([{"Id": "sha256:test"}])
        if "diff" in command:
            return b""
        if "ls-files" in command:
            return b"run.py\0"
        if "rev-parse" in command:
            return "test\n"
        raise AssertionError(f"Unexpected command: {command}")

    def test_main_isolates_sixteen_cases_and_cleans_before_next_case(self):
        with tempfile.TemporaryDirectory() as directory:
            runner = Path(directory) / "runner"
            runner.mkdir()
            (runner / "run.py").write_text("upstream-original")
            registry = {
                name: {"image": name, "role": role}
                for name, role in (
                    ("webtransport-go", "both"),
                    ("flupke-webtransport", "both"),
                    ("ngtcp2", "both"),
                    ("firefox", "client"),
                )
            }
            (runner / "implementations_webtransport.json").write_text(
                json.dumps(registry)
            )
            output = Path(directory) / "result"
            events = []
            originals = {}

            def run(command, local_runner, console, timeout):
                self.assertTrue(not events or events[-1] == "cleanup")
                case = command[command.index("-t") + 1]
                client = command[command.index("-c") + 1]
                server = command[command.index("-s") + 1]
                self.assertNotIn(",", case + client + server)
                events.append((client, server, case))
                self.assertEqual(
                    (local_runner / "run.py").read_text(), "upstream-original"
                )
                abbr = dict((case, abbr) for abbr, case in CASES)[case]
                original = json.dumps(
                    {
                        "clients": [client],
                        "servers": [server],
                        "results": [
                            [{"abbr": abbr, "name": case, "result": "succeeded"}]
                        ],
                    },
                    indent=3,
                )
                result_file = Path(command[command.index("-j") + 1])
                result_file.write_text(original)
                originals[result_file] = original
                console.write_text("original upstream console\n")
                return 0, False

            def cleanup(local_runner):
                self.assertEqual(local_runner, output.resolve() / "runner")
                events.append("cleanup")
                return ["owned"]

            arguments = [
                "run_matrix.py",
                "--runner",
                str(runner),
                "--output",
                str(output),
            ]
            with patch("sys.argv", arguments), patch(
                "run_matrix.subprocess.check_output", side_effect=self.check_output
            ), patch("run_matrix.run_case", side_effect=run), patch(
                "run_matrix.cleanup_containers", side_effect=cleanup
            ):
                self.assertEqual(main(), 0)
            self.assertEqual(len(events), 32)
            self.assertEqual(len(set(events[::2])), 16)
            metadata = json.loads((output / "provenance.json").read_text())
            self.assertEqual(len({inv["logs"] for inv in metadata["invocations"]}), 16)
            self.assertEqual(len(originals), 16)
            for result_file, original in originals.items():
                self.assertEqual(result_file.read_text(), original)
                self.assertTrue(result_file.with_suffix(".log").exists())
            combined = json.loads((output / "results.json").read_text())
            self.assertEqual(
                sum(
                    record["result"] == "succeeded"
                    for pair in combined["results"]
                    for record in pair
                ),
                16,
            )

    def test_main_propagates_failed_missing_cases_timeouts_and_runner_errors(self):
        with tempfile.TemporaryDirectory() as directory:
            runner = Path(directory) / "runner"
            runner.mkdir()
            (runner / "run.py").write_text("")
            (runner / "implementations_webtransport.json").write_text("{}")
            for state, runner_status, expected in (
                ("succeeded", 0, 0),
                ("failed", 0, 1),
                ("succeeded", -9, 1),
                ("succeeded", 124, 1),
                (None, 0, 1),
            ):
                with self.subTest(state=state, runner_status=runner_status):
                    output = Path(directory) / f"{state}-{runner_status}"

                    def run(command, local_runner, console, timeout):
                        case = command[command.index("-t") + 1]
                        abbr = dict((case, abbr) for abbr, case in CASES)[case]
                        result = {
                            "clients": ["xquic"],
                            "servers": ["xquic"],
                            "results": [
                                [
                                    {"abbr": abbr, "result": state},
                                ]
                            ],
                        }
                        if state is not None:
                            Path(command[command.index("-j") + 1]).write_text(
                                json.dumps(result)
                            )
                        return runner_status, runner_status == 124

                    arguments = [
                        "run_matrix.py",
                        "--runner",
                        str(runner),
                        "--output",
                        str(output),
                        "--peers",
                        "",
                    ]
                    with patch("sys.argv", arguments), patch(
                        "run_matrix.subprocess.check_output",
                        side_effect=self.check_output,
                    ), patch("run_matrix.run_case", side_effect=run), patch(
                        "run_matrix.cleanup_containers", return_value=[]
                    ) as cleanup:
                        self.assertEqual(main(), expected)
                        self.assertEqual(cleanup.call_count, 2)
                    self.assertTrue((output / "results.json").is_file())

    def test_cleanup_requires_exact_inspected_directory_label(self):
        runner = Path("/task/results/runner")
        containers = [
            {"Id": "owned", "Config": {"Labels": {OWNER_LABEL: str(runner)}}},
            {"Id": "foreign", "Config": {"Labels": {OWNER_LABEL: "/other/runner"}}},
            {"Id": "unlabeled", "Config": {"Labels": None}},
        ]
        with patch(
            "run_matrix.subprocess.check_output",
            side_effect=["owned\nforeign\nunlabeled\n", json.dumps(containers), ""],
        ) as inspect, patch("run_matrix.subprocess.run") as remove:
            self.assertEqual(cleanup_containers(runner), ["owned"])
            self.assertIn(
                f"label={OWNER_LABEL}={runner}", inspect.call_args_list[0].args[0]
            )
            self.assertEqual(
                remove.call_args.args[0], ["docker", "container", "rm", "-f", "owned"]
            )
        with patch("run_matrix.subprocess.check_output", side_effect=["", ""]), patch(
            "run_matrix.subprocess.run"
        ) as remove:
            self.assertEqual(cleanup_containers(runner), [])
            remove.assert_not_called()
        with patch("run_matrix.subprocess.check_output", side_effect=["", "leftover"]):
            with self.assertRaises(RuntimeError):
                cleanup_containers(runner)

    def test_main_stops_if_cleanup_fails_and_cleans_after_launch_error(self):
        with tempfile.TemporaryDirectory() as directory:
            runner = Path(directory) / "runner"
            runner.mkdir()
            (runner / "run.py").write_text("")
            (runner / "implementations_webtransport.json").write_text("{}")
            for cleanup_error in (False, True):
                output = Path(directory) / str(cleanup_error)
                arguments = [
                    "run_matrix.py",
                    "--runner",
                    str(runner),
                    "--output",
                    str(output),
                    "--peers",
                    "",
                ]
                with patch("sys.argv", arguments), patch(
                    "run_matrix.subprocess.check_output", side_effect=self.check_output
                ), patch(
                    "run_matrix.run_case", side_effect=OSError("launch failed")
                ) as run, patch(
                    "run_matrix.cleanup_containers",
                    side_effect=(
                        RuntimeError("cleanup failed") if cleanup_error else None
                    ),
                    return_value=[],
                ) as cleanup:
                    self.assertEqual(main(), 1)
                    self.assertEqual(run.call_count, 1 if cleanup_error else 2)
                    self.assertEqual(cleanup.call_count, run.call_count)
                metadata = json.loads((output / "provenance.json").read_text())
                self.assertEqual(metadata["invocations"][0]["error"], "launch failed")
                self.assertEqual(
                    "cleanup_error" in metadata["invocations"][0], cleanup_error
                )
                result = json.loads((output / "results.json").read_text())
                self.assertTrue(
                    all(record["result"] is None for record in result["results"][0])
                )

    def test_run_case_reaps_own_process_group_after_timeout_and_exit(self):
        for timeout, status in ((False, 0), (False, 9), (True, 124)):
            waits = iter(
                (
                    [subprocess.TimeoutExpired("run.py", 1), -9]
                    if timeout
                    else [status, status]
                )
            )

            def wait(**kwargs):
                value = next(waits)
                if isinstance(value, Exception):
                    raise value
                return value

            process = SimpleNamespace(pid=12345, wait=wait)
            with tempfile.TemporaryDirectory() as directory, patch(
                "run_matrix.subprocess.Popen", return_value=process
            ) as start, patch("run_matrix.os.killpg") as kill:
                console = Path(directory) / "case.log"
                self.assertEqual(
                    run_case(["run.py"], Path(directory), console, 1), (status, timeout)
                )
                self.assertTrue(start.call_args.kwargs["start_new_session"])
                kill.assert_called_once_with(12345, signal.SIGKILL)
                self.assertEqual("Wrapper timeout" in console.read_text(), timeout)


if __name__ == "__main__":
    unittest.main()
