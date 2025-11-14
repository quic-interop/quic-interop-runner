import io
import json
import logging
import multiprocessing
import os
import random
import re
import shutil
import statistics
import string
import subprocess
import sys
import tempfile
import threading
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime
from typing import Callable, List, Tuple, Optional

import prettytable
from termcolor import colored

import testcases
from result import TestResult
from testcases import Perspective


def random_string(length: int):
    """Generate a random string of fixed length"""
    letters = string.ascii_lowercase
    return "".join(random.choice(letters) for i in range(length))


class MeasurementResult:
    result: TestResult
    details: str


class LogFileFormatter(logging.Formatter):
    def format(self, record):
        msg = super(LogFileFormatter, self).format(record)
        # remove color control characters
        return re.compile(r"\x1B[@-_][0-?]*[ -/]*[@-~]").sub("", msg)


class LogRecordCapturingHandler(logging.Handler):
    """Handler that captures log records with their levels for later replay."""

    def __init__(self):
        super().__init__()
        self.records = []

    def emit(self, record):
        # Store just the level and the formatted message
        self.records.append(
            {
                "level": record.levelno,
                "msg": self.format(record),
            }
        )


class InteropRunner:
    _start_time: datetime = datetime.now()
    test_results = {}  # dict[str, dict[str, dict[testcases.TestCase, TestResult]]]
    measurement_results = {}
    compliant: dict[str, bool] = {}
    _implementations: dict[str, dict[str, str]] = {}
    _client_server_pairs: list[tuple[str, str]] = []
    _tests: list[testcases.TestCase] = []
    _measurements: list[testcases.Measurement] = []
    _output = ""
    _markdown = False
    _log_dir = ""
    _save_files = False
    _no_auto_unsupported: list[str] = []
    # Shared class variables for subnet allocation across all instances
    _subnet_allocator_lock = threading.Lock()
    _allocated_subnets: set[int] = set()
    _next_subnet_index = 0

    def __init__(
        self,
        implementations: dict,
        client_server_pairs: List[Tuple[str, str]],
        tests: List[testcases.TestCase],
        measurements: List[testcases.Measurement],
        output: str,
        markdown: bool,
        debug: bool,
        save_files=False,
        log_dir="",
        parallel=None,
        no_auto_unsupported=None,
    ):
        logger = logging.getLogger()
        logger.setLevel(logging.DEBUG)
        console = logging.StreamHandler(stream=sys.stderr)
        if debug:
            console.setLevel(logging.DEBUG)
        else:
            console.setLevel(logging.INFO)
        logger.addHandler(console)
        self._tests = tests
        self._measurements = measurements
        self._client_server_pairs = client_server_pairs
        self._implementations = implementations
        self._output = output
        self._markdown = markdown
        self._log_dir = log_dir
        self._save_files = save_files
        if no_auto_unsupported is None:
            self._no_auto_unsupported = []
        else:
            self._no_auto_unsupported = no_auto_unsupported

        total_cores = multiprocessing.cpu_count()
        if parallel is None or parallel <= 0:
            self._parallel = total_cores
        else:
            self._parallel = parallel
        logging.info(
            "Running with %d parallel tests (system has %d cores)",
            self._parallel,
            total_cores,
        )

        if len(self._log_dir) == 0:
            self._log_dir = "logs_{:%Y-%m-%dT%H:%M:%S}".format(self._start_time)
        if os.path.exists(self._log_dir):
            sys.exit("Log dir " + self._log_dir + " already exists.")
        logging.info("Saving logs to %s.", self._log_dir)
        for client, server in client_server_pairs:
            for test in self._tests:
                self.test_results.setdefault(server, {}).setdefault(
                    client, {}
                ).setdefault(test, {})
            for measurement in measurements:
                self.measurement_results.setdefault(server, {}).setdefault(
                    client, {}
                ).setdefault(measurement, {})

    def _is_unsupported(self, lines: List[str]) -> bool:
        return any("exited with code 127" in str(line) for line in lines) or any(
            "exit status 127" in str(line) for line in lines
        )

    def _docker_compose(
        self,
        action: str,
        project_name: str,
        env: Optional[dict[str, str]] = None,
        containers: str = "",
        timeout: Optional[int] = None,
        check: bool = True,
    ) -> subprocess.CompletedProcess:
        cmd = (
            (" ".join(f"{k}={v} " for k, v in env.items()) if env else "")
            + f"docker compose --project-name {project_name} --env-file empty.env {action} {containers}"
        )
        return subprocess.run(
            cmd,
            # env=env,
            shell=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            timeout=timeout,
            check=check,
        )

    def _check_impl_is_compliant(self, name: str) -> bool:
        """check if an implementation return UNSUPPORTED for unknown test cases"""
        if name in self.compliant:
            logging.debug(
                "%s already tested for compliance: %s", name, str(self.compliant)
            )
            return self.compliant[name]

        (subnet_index, subnet_params) = self._allocate_subnet()
        project_name = f"compliance_{name}_{subnet_index}"
        client_log_dir = tempfile.TemporaryDirectory(dir="/tmp", prefix="logs_client_")
        server_log_dir = tempfile.TemporaryDirectory(dir="/tmp", prefix="logs_server_")
        www_dir = tempfile.TemporaryDirectory(dir="/tmp", prefix="compliance_www_")
        certs_dir = tempfile.TemporaryDirectory(dir="/tmp", prefix="compliance_certs_")
        downloads_dir = tempfile.TemporaryDirectory(
            dir="/tmp", prefix="compliance_downloads_"
        )
        params = {
            "CERTS": certs_dir.name,
            "TESTCASE_CLIENT": random_string(6),
            "TESTCASE_SERVER": random_string(6),
            "CLIENT_LOGS": client_log_dir.name,
            "SERVER_LOGS": server_log_dir.name,
            "WWW": www_dir.name,
            "DOWNLOADS": downloads_dir.name,
            "SCENARIO": '"simple-p2p --delay=15ms --bandwidth=10Mbps --queue=25"',
            "CLIENT": self._implementations[name]["image"],
            "SERVER": self._implementations[name]["image"],
        }

        testcases.generate_cert_chain(certs_dir.name)

        # check that client and server are capable of returning UNSUPPORTED
        self.compliant[name] = True
        for role, containers, opt in [
            ("client", "sim client", "--timeout 0 --abort-on-container-exit"),
            ("server", "server", ""),
        ]:
            logging.debug("Checking compliance of %s %s", name, role)
            output = self._docker_compose(
                f"up {opt} --renew-anon-volumes",
                project_name,
                subnet_params | params,
                containers,
                check=False,
            )
            if not self._is_unsupported(output.stdout.splitlines()):
                logging.error("%s %s not compliant.", name, role)
                logging.debug(output.stdout.decode("utf-8", errors="replace"))
                self.compliant[name] = False
                break
            logging.debug("%s %s compliant.", name, role)

        self._docker_compose("down", project_name)
        self._release_subnet(subnet_index)
        return True

    def _postprocess_results(self):
        clients = list(set(client for client, _ in self._client_server_pairs))
        servers = list(set(server for _, server in self._client_server_pairs))
        questionable = [TestResult.FAILED, TestResult.UNSUPPORTED]
        # If a client failed a test against all servers, make the test unsupported for the client
        if len(servers) > 1:
            for c in set(clients) - set(self._no_auto_unsupported):
                for t in self._tests:
                    if all(self.test_results[s][c][t] in questionable for s in servers):
                        logging.info(
                            f"Client {c} failed or did not support test {t.name()} "
                            + 'against all servers, marking the entire test as "unsupported"'
                        )
                        for s in servers:
                            self.test_results[s][c][t] = TestResult.UNSUPPORTED
        # If a server failed a test against all clients, make the test unsupported for the server
        if len(clients) > 1:
            for s in set(servers) - set(self._no_auto_unsupported):
                for t in self._tests:
                    if all(self.test_results[s][c][t] in questionable for c in clients):
                        logging.info(
                            f"Server {s} failed or did not support test {t.name()} "
                            + 'against all clients, marking the entire test as "unsupported"'
                        )
                        for c in clients:
                            self.test_results[s][c][t] = TestResult.UNSUPPORTED

    def _print_results(self):
        """print the interop table"""
        logging.info("Run took %s", datetime.now() - self._start_time)

        def get_letters(result):
            return (
                result.symbol()
                + "("
                + ",".join(
                    [test.abbreviation() for test in cell if cell[test] is result]
                )
                + ")"
            )

        if len(self._tests) > 0:
            t = prettytable.PrettyTable()
            if self._markdown:
                t.set_style(prettytable.MARKDOWN)
            else:
                t.hrules = prettytable.ALL
                t.vrules = prettytable.ALL
            rows = {}
            columns = {}
            for client, server in self._client_server_pairs:
                columns[server] = {}
                row = rows.setdefault(client, {})
                cell = self.test_results[server][client]
                br = "<br>" if self._markdown else "\n"
                res = colored(get_letters(TestResult.SUCCEEDED), "green") + br
                res += colored(get_letters(TestResult.UNSUPPORTED), "grey") + br
                res += colored(get_letters(TestResult.FAILED), "red")
                row[server] = res

            t.field_names = [""] + [column for column, _ in columns.items()]
            for client, results in rows.items():
                row = [client]
                for server, _ in columns.items():
                    row += [results.setdefault(server, "")]
                t.add_row(row)
            print(t)

        if len(self._measurements) > 0:
            t = prettytable.PrettyTable()
            if self._markdown:
                t.set_style(prettytable.MARKDOWN)
            else:
                t.hrules = prettytable.ALL
                t.vrules = prettytable.ALL
            rows = {}
            columns = {}
            for client, server in self._client_server_pairs:
                columns[server] = {}
                row = rows.setdefault(client, {})
                cell = self.measurement_results[server][client]
                results = []
                for measurement in self._measurements:
                    res = cell[measurement]
                    if not hasattr(res, "result"):
                        continue
                    if res.result == TestResult.SUCCEEDED:
                        results.append(
                            colored(
                                measurement.abbreviation() + ": " + res.details,
                                "green",
                            )
                        )
                    elif res.result == TestResult.UNSUPPORTED:
                        results.append(colored(measurement.abbreviation(), "grey"))
                    elif res.result == TestResult.FAILED:
                        results.append(colored(measurement.abbreviation(), "red"))
                row[server] = "\n".join(results)
            t.field_names = [""] + [column for column, _ in columns.items()]
            for client, results in rows.items():
                row = [client]
                for server, _ in columns.items():
                    row += [results.setdefault(server, "")]
                t.add_row(row)
            print(t)

    def _export_results(self):
        if not self._output:
            return
        clients = list(set(client for client, _ in self._client_server_pairs))
        servers = list(set(server for _, server in self._client_server_pairs))
        out = {
            "start_time": self._start_time.timestamp(),
            "end_time": datetime.now().timestamp(),
            "log_dir": self._log_dir,
            "servers": servers,
            "clients": clients,
            "urls": {x: self._implementations[x]["url"] for x in clients + servers},
            "tests": {
                x.abbreviation(): {
                    "name": x.name(),
                    "desc": x.desc(),
                }
                for x in self._tests + self._measurements
            },
            "quic_draft": testcases.QUIC_DRAFT,
            "quic_version": testcases.QUIC_VERSION,
            "results": [],
            "measurements": [],
        }

        for client in clients:
            for server in servers:
                results = []
                for test in self._tests:
                    r = None
                    if hasattr(self.test_results[server][client][test], "value"):
                        r = self.test_results[server][client][test].value
                    results.append(
                        {
                            "abbr": test.abbreviation(),
                            "name": test.name(),  # TODO: remove
                            "result": r,
                        }
                    )
                out["results"].append(results)

                measurements = []
                for measurement in self._measurements:
                    res = self.measurement_results[server][client][measurement]
                    if not hasattr(res, "result"):
                        continue
                    measurements.append(
                        {
                            "name": measurement.name(),  # TODO: remove
                            "abbr": measurement.abbreviation(),
                            "result": res.result.value,
                            "details": res.details,
                        }
                    )
                out["measurements"].append(measurements)

        f = open(self._output, "w", encoding="utf-8")
        json.dump(out, f)
        f.close()

    def _copy_logs(
        self, container: str, log_dir: tempfile.TemporaryDirectory, project_name: str
    ):
        # Match container names based on project name
        # e.g., for project "interop_test" and container "sim", matches "interop_test-sim-1"
        cmd = (
            "docker cp \"$(docker ps -a --format '{{.ID}} {{.Names}}' | awk '/"
            + project_name
            + "-"
            + container
            + "(-[0-9]+)?$/ {print $1}' | head -1)\":/logs/. "
            + log_dir.name
        )
        r = subprocess.run(
            cmd,
            shell=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            check=True,
        )
        if r.returncode != 0:
            logging.info(
                "Copying logs from %s (project: %s) failed: %s",
                container,
                project_name,
                r.stdout.decode("utf-8", errors="replace"),
            )

    def _run_test(
        self,
        server: str,
        client: str,
        test: Callable[[], testcases.TestCase],
    ) -> Tuple[TestResult, float]:
        start_time = datetime.now()
        sim_log_dir = tempfile.TemporaryDirectory(dir="/tmp", prefix="logs_sim_")
        server_log_dir = tempfile.TemporaryDirectory(dir="/tmp", prefix="logs_server_")
        client_log_dir = tempfile.TemporaryDirectory(dir="/tmp", prefix="logs_client_")
        log_file = tempfile.NamedTemporaryFile(dir="/tmp", prefix="output_log_")
        log_handler = logging.FileHandler(log_file.name)
        log_handler.setLevel(logging.DEBUG)

        formatter = LogFileFormatter("%(asctime)s %(message)s")
        log_handler.setFormatter(formatter)
        logging.getLogger().addHandler(log_handler)

        (subnet_index, subnet_params) = self._allocate_subnet()

        testcase = test(
            sim_log_dir=sim_log_dir,
            client_keylog_file=client_log_dir.name + "/keys.log",
            server_keylog_file=server_log_dir.name + "/keys.log",
            client_v4=subnet_params["CLIENT_V4_ADDR"],
            client_v6=subnet_params["CLIENT_V6_ADDR"],
            server_v4=subnet_params["SERVER_V4_ADDR"],
            server_v6=subnet_params["SERVER_V6_ADDR"],
        )
        print(
            "Server: "
            + server
            + ". Client: "
            + client
            + ". Running test case: "
            + str(testcase)
        )

        reqs = " ".join([testcase.urlprefix() + p for p in testcase.get_paths()])
        logging.debug("Requests: %s", reqs)
        project_name = f"interop_{server}_{client}_{testcase.name()}_{subnet_index}"
        containers = "sim client server " + " ".join(testcase.additional_containers())
        status = TestResult.FAILED
        output = None
        expired = False
        try:
            r = self._docker_compose(
                "up --abort-on-container-exit --timeout 1",
                project_name,
                subnet_params
                | {
                    "WAITFORSERVER": "server:443",
                    "CERTS": testcase.certs_dir(),
                    "TESTCASE_SERVER": testcase.testname(Perspective.SERVER),
                    "TESTCASE_CLIENT": testcase.testname(Perspective.CLIENT),
                    "WWW": testcase.www_dir(),
                    "DOWNLOADS": testcase.download_dir(),
                    "SERVER_LOGS": server_log_dir.name,
                    "CLIENT_LOGS": client_log_dir.name,
                    "SCENARIO": "'" + testcase.scenario() + "'",
                    "CLIENT": self._implementations[client]["image"],
                    "SERVER": self._implementations[server]["image"],
                    "REQUESTS": "'" + reqs + " ".join(testcase.additional_envs()) + "'",
                },
                containers,
                testcase.timeout(),
            )
            output = r.stdout
        except subprocess.TimeoutExpired as ex:
            logging.error("Test timed out after %ds", testcase.timeout())
            output = ex.stdout
            expired = True
        except subprocess.CalledProcessError as ex:
            logging.error("Test failed with error: %s", ex)
            output = ex.stdout

        if output is not None:
            logging.debug(output.decode("utf-8", errors="replace"))

        if expired:
            logging.debug("Test failed: took longer than %ds.", testcase.timeout())
            self._docker_compose("stop", project_name, None, containers, timeout=60)

        # copy the pcaps from the simulator
        self._copy_logs("sim", sim_log_dir, project_name)
        self._copy_logs("client", client_log_dir, project_name)
        self._copy_logs("server", server_log_dir, project_name)

        if not expired and output is not None:
            lines = output.decode("utf-8", errors="replace").splitlines()
            if self._is_unsupported(lines):
                status = TestResult.UNSUPPORTED
            elif any(
                re.search(r"client.*exited with code 0", str(line)) for line in lines
            ):
                try:
                    status = testcase.check()
                except FileNotFoundError as e:
                    logging.error("testcase.check() threw FileNotFoundError: %s", e)
                    status = TestResult.FAILED

        # save logs
        logging.getLogger().removeHandler(log_handler)
        log_handler.close()
        if status == TestResult.FAILED or status == TestResult.SUCCEEDED:
            log_dir = self._log_dir + "/" + server + "_" + client + "/" + str(testcase)
            shutil.copytree(server_log_dir.name, log_dir + "/server")
            shutil.copytree(client_log_dir.name, log_dir + "/client")
            shutil.copytree(sim_log_dir.name, log_dir + "/sim")
            shutil.copyfile(log_file.name, log_dir + "/output.txt")
            if self._save_files and status == TestResult.FAILED:
                shutil.copytree(testcase.www_dir(), log_dir + "/www")
                try:
                    shutil.copytree(testcase.download_dir(), log_dir + "/downloads")
                except Exception as exception:
                    # This logging will now go to console since we restored handlers
                    logging.info("Could not copy downloaded files: %s", exception)

        self._docker_compose("down", project_name)
        self._release_subnet(subnet_index)
        testcase.cleanup()
        server_log_dir.cleanup()
        client_log_dir.cleanup()
        sim_log_dir.cleanup()
        logging.debug(
            "Test: %s took %ss, status: %s",
            str(testcase),
            (datetime.now() - start_time).total_seconds(),
            str(status),
        )

        # measurements also have a value
        if hasattr(testcase, "result"):
            value = testcase.result()
        else:
            value = None

        return status, value

    def _run_measurement(
        self, server: str, client: str, test: Callable[[], testcases.Measurement]
    ) -> MeasurementResult:
        values = []
        for _ in range(0, test.repetitions()):
            result, value = self._run_test(server, client, test)
            if result != TestResult.SUCCEEDED:
                res = MeasurementResult()
                res.result = result
                res.details = ""
                return res
            values.append(value)

        logging.debug(values)
        res = MeasurementResult()
        res.result = TestResult.SUCCEEDED
        res.details = "{:.0f} (± {:.0f}) {}".format(
            statistics.mean(values), statistics.stdev(values), test.unit()
        )
        return res

    def _allocate_subnet(self):
        """Allocate a unique subnet range for a test"""
        with self._subnet_allocator_lock:
            # Find next available subnet index
            while InteropRunner._next_subnet_index in InteropRunner._allocated_subnets:
                InteropRunner._next_subnet_index += 1

            subnet_index = InteropRunner._next_subnet_index
            InteropRunner._allocated_subnets.add(subnet_index)
            InteropRunner._next_subnet_index += 1

            subnet_v4 = f"10.{subnet_index}"
            subnet_v6 = f"fd00:cafe:{subnet_index:04x}"

            params = {
                "SUBNET_V4_PREFIX": "16",
                "SUBNET_V4": subnet_v4,
                "SUBNET_V4_SUBNET": ".0.0",
                "V4_PREFIX": "24",
                "CLIENT_V4_NET": f"{subnet_v4}.10",
                "CLIENT_V4_ADDR": f"{subnet_v4}.10.10",
                "SERVER_V4_NET": f"{subnet_v4}.222",
                "SERVER_V4_ADDR": f"{subnet_v4}.222.222",
                "SUBNET_V6_PREFIX": "48",
                "SUBNET_V6": subnet_v6,
                "V6_PREFIX": "64",
                "CLIENT_V6_NET": f"{subnet_v6}:10",
                "CLIENT_V6_ADDR": f"{subnet_v6}:10::10",
                "SERVER_V6_NET": f"{subnet_v6}:222",
                "SERVER_V6_ADDR": f"{subnet_v6}:222::222",
            }

            return (subnet_index, params)

    def _release_subnet(self, subnet_index):
        """Release a subnet range after test completion"""
        with self._subnet_allocator_lock:
            InteropRunner._allocated_subnets.discard(subnet_index)

    def run(self):
        """run the interop test suite and output the table"""

        nr_failed = 0
        for client, server in self._client_server_pairs:
            logging.debug(
                "Running with server %s (%s) and client %s (%s)",
                server,
                self._implementations[server]["image"],
                client,
                self._implementations[client]["image"],
            )

            # Set up a handler to capture log records with their levels for this client/server pair
            capture_handler = LogRecordCapturingHandler()

            # Find and remove console handlers, saving them for later restoration
            root_logger = logging.getLogger()
            console_handlers = []
            for handler in root_logger.handlers[
                :
            ]:  # Use slice to avoid modifying list during iteration
                if (
                    isinstance(handler, logging.StreamHandler)
                    and handler.stream == sys.stderr
                ):
                    console_handlers.append(handler)
                    # Copy the console handler's level and formatter to the capture handler
                    capture_handler.setLevel(handler.level)
                    capture_handler.setFormatter(handler.formatter)
                    root_logger.removeHandler(handler)

            # Add the capture handler to capture logs with levels
            root_logger.addHandler(capture_handler)

            # Check compliance (now captured)
            compliant = self._check_impl_is_compliant(
                server
            ) and self._check_impl_is_compliant(client)

            if not compliant:
                logging.info("Not compliant, skipping")
                # Restore console handlers before continuing
                root_logger.removeHandler(capture_handler)
                for handler in console_handlers:
                    root_logger.addHandler(handler)
                continue

            # run the test cases
            with ThreadPoolExecutor(max_workers=self._parallel) as executor:
                # Submit all tests to the executor
                futures = {}
                for testcase in self._tests:
                    future = executor.submit(self._run_test, server, client, testcase)
                    futures[future] = testcase
                    # Small delay to prevent thundering herd on Docker daemon
                    time.sleep(0.2)

                # Collect results as they complete
                for future in as_completed(futures):
                    testcase = futures[future]
                    try:
                        status, _ = future.result()
                        self.test_results[server][client][testcase] = status
                        if status == TestResult.FAILED:
                            nr_failed += 1
                        print(f"Completed: {testcase.name()} - {status}")

                    except Exception as e:
                        self.test_results[server][client][testcase] = TestResult.FAILED
                        nr_failed += 1
                        print(f"Test {testcase.name()} failed with exception: {e}")
                        import traceback
                        print(traceback.format_exc())

            # run the measurements
            for measurement in self._measurements:
                res = self._run_measurement(server, client, measurement)
                self.measurement_results[server][client][measurement] = res

            # Restore console handlers and replay captured logs at their original levels
            root_logger.removeHandler(capture_handler)
            for handler in console_handlers:
                root_logger.addHandler(handler)

            # Replay captured log records at their original levels
            for record in capture_handler.records:
                # Only output if the record level meets the threshold
                for handler in root_logger.handlers:
                    if (
                        isinstance(handler, logging.StreamHandler)
                        and handler.stream == sys.stderr
                    ):
                        if record["level"] >= handler.level:
                            print(record["msg"], file=sys.stderr)
                            break  # Only print once per record

        self._postprocess_results()
        self._print_results()
        self._export_results()
        return nr_failed
