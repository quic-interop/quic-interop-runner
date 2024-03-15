import json
import logging
import os
from unique_random_slugs import generate_slug
import re
import shutil
import statistics
import subprocess
import sys
import tempfile
from datetime import datetime
from typing import Callable, List, Tuple
import prettytable
from termcolor import colored

import testcases_quic
from result import TestResult
from testcase import Perspective, QUIC_VERSION


class MeasurementResult:
    result = TestResult
    details = str


class LogFileFormatter(logging.Formatter):
    def format(self, record):
        msg = super(LogFileFormatter, self).format(record)
        # remove color control characters
        return re.compile(r"\x1B[@-_][0-?]*[ -/]*[@-~]").sub("", msg)


class InteropRunner:
    _start_time = 0
    test_results = {}
    measurement_results = {}
    compliant = {}
    _implementations = {}
    _client_server_pairs = []
    _tests = []
    _measurements = []
    _output = ""
    _markdown = False
    _log_dir = ""
    _save_files = False
    _no_auto_unsupported = []

    def __init__(
        self,
        implementations: dict,
        client_server_pairs: List[Tuple[str, str]],
        tests: List[testcases_quic.TestCase],
        measurements: List[testcases_quic.Measurement],
        output: str,
        markdown: bool,
        debug: bool,
        save_files=False,
        log_dir="",
        no_auto_unsupported=[],
    ):
        logger = logging.getLogger()
        logger.setLevel(logging.DEBUG)
        console = logging.StreamHandler(stream=sys.stderr)
        if debug:
            console.setLevel(logging.DEBUG)
        else:
            console.setLevel(logging.INFO)
        logger.addHandler(console)
        self._start_time = datetime.now()
        self._tests = tests
        self._measurements = measurements
        self._client_server_pairs = client_server_pairs
        self._implementations = implementations
        self._output = output
        self._markdown = markdown
        self._log_dir = log_dir
        self._save_files = save_files
        self._no_auto_unsupported = no_auto_unsupported
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

    def _check_impl_is_compliant(self, name: str, role: Perspective) -> bool:
        """Check if an implementation returns UNSUPPORTED for unknown test cases."""
        if name in self.compliant and role in self.compliant[name]:
            logging.debug(
                "%s already tested for %s compliance: %s",
                name,
                role.name.lower(),
                str(self.compliant[name][role]),
            )
            return self.compliant[name][role]

        self.compliant.setdefault(name, {})

        client_log_dir = tempfile.TemporaryDirectory(dir="/tmp", prefix="logs_client_")
        www_dir = tempfile.TemporaryDirectory(dir="/tmp", prefix="compliance_www_")
        certs_dir = tempfile.TemporaryDirectory(dir="/tmp", prefix="compliance_certs_")
        downloads_dir = tempfile.TemporaryDirectory(
            dir="/tmp", prefix="compliance_downloads_"
        )

        testcases_quic.generate_cert_chain(certs_dir.name)

        if role == Perspective.CLIENT:
            # check that the client is capable of returning UNSUPPORTED
            logging.debug("Checking compliance of %s client", name)
            cmd = (
                "CERTS=" + certs_dir.name + " "
                "TESTCASE_CLIENT=" + generate_slug() + " "
                "SERVER_LOGS=/dev/null "
                "CLIENT_LOGS=" + client_log_dir.name + " "
                "WWW=" + www_dir.name + " "
                "DOWNLOADS=" + downloads_dir.name + " "
                'SCENARIO="simple-p2p --delay=15ms --bandwidth=10Mbps --queue=25" '
                "CLIENT=" + self._implementations[name]["image"] + " "
                "SERVER="
                + self._implementations[name]["image"]
                + " "  # only needed so docker compose doesn't complain
                "docker compose --env-file empty.env up --timeout 0 --abort-on-container-exit -V sim client"
            )
            output = subprocess.run(
                cmd, shell=True, stdout=subprocess.PIPE, stderr=subprocess.STDOUT
            )
            if not self._is_unsupported(output.stdout.splitlines()):
                logging.error("%s client not compliant.", name)
                logging.debug("%s", output.stdout.decode("utf-8", errors="replace"))
                self.compliant[name][role] = False
                return False
            logging.debug("%s client compliant.", name)
        elif role == Perspective.SERVER:
            # check that the server is capable of returning UNSUPPORTED
            logging.debug("Checking compliance of %s server", name)
            server_log_dir = tempfile.TemporaryDirectory(
                dir="/tmp", prefix="logs_server_"
            )
            cmd = (
                "CERTS=" + certs_dir.name + " "
                "TESTCASE_SERVER=" + generate_slug() + " "
                "SERVER_LOGS=" + server_log_dir.name + " "
                "CLIENT_LOGS=/dev/null "
                "WWW=" + www_dir.name + " "
                "DOWNLOADS=" + downloads_dir.name + " "
                "CLIENT="
                + self._implementations[name]["image"]
                + " "  # only needed so docker compose doesn't complain
                "SERVER=" + self._implementations[name]["image"] + " "
                "docker compose --env-file empty.env up -V server"
            )
            output = subprocess.run(
                cmd, shell=True, stdout=subprocess.PIPE, stderr=subprocess.STDOUT
            )
            if not self._is_unsupported(output.stdout.splitlines()):
                logging.error("%s server not compliant.", name)
                logging.debug("%s", output.stdout.decode("utf-8", errors="replace"))
                self.compliant[name][role] = False
                return False
            logging.debug("%s server compliant.", name)
        else:
            raise ValueError(f"Unknown perspective for compliance check: {role}")

        # remember compliance test outcome for this role
        self.compliant[name][role] = True
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
                        print(
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
                        print(
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
            "quic_version": QUIC_VERSION,
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

        f = open(self._output, "w")
        json.dump(out, f)
        f.close()

    def _copy_logs(self, container: str, dir: tempfile.TemporaryDirectory):
        cmd = (
            "docker cp \"$(docker ps -a --format '{{.ID}} {{.Names}}' | awk '/^.* "
            + container
            + "$/ {print $1}')\":/logs/. "
            + dir.name
        )
        r = subprocess.run(
            cmd,
            shell=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
        )
        if r.returncode != 0:
            logging.info(
                "Copying logs from %s failed: %s",
                container,
                r.stdout.decode("utf-8", errors="replace"),
            )

    def _run_testcase(
        self, server: str, client: str, test: Callable[[], testcases_quic.TestCase]
    ) -> TestResult:
        return self._run_test(server, client, None, test)[0]

    def _run_test(
        self,
        server: str,
        client: str,
        log_dir_prefix: None,
        fn: Callable[[], testcases_quic.TestCase],
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

        test = fn(
            sim_log_dir=sim_log_dir,
            client_keylog_file=client_log_dir.name + "/keys.log",
            server_keylog_file=server_log_dir.name + "/keys.log",
        )
        print(
            "Server: "
            + server
            + ". Client: "
            + client
            + ". Running test case: "
            + str(test)
        )

        reqs = " ".join([test.urlprefix() + p for p in test.get_paths()])
        logging.debug("Requests: %s", reqs)
        params = (
            "WAITFORSERVER=server:443 "
            "CERTS=" + test.certs_dir() + " "
            "TESTCASE_SERVER=" + test.testname(Perspective.SERVER) + " "
            "TESTCASE_CLIENT=" + test.testname(Perspective.CLIENT) + " "
            "WWW=" + test.www_dir() + " "
            "DOWNLOADS=" + test.download_dir() + " "
            "SERVER_LOGS=" + server_log_dir.name + " "
            "CLIENT_LOGS=" + client_log_dir.name + " "
            'SCENARIO="{}" '
            "CLIENT=" + self._implementations[client]["image"] + " "
            "SERVER=" + self._implementations[server]["image"] + " "
            'REQUESTS="' + reqs + '" '
        ).format(test.scenario())
        params += " ".join(test.additional_envs())
        containers = "sim client server " + " ".join(test.additional_containers())
        cmd = (
            params
            + " docker compose --env-file empty.env up --abort-on-container-exit --timeout 1 "
            + containers
        )
        logging.debug("Command: %s", cmd)

        status = TestResult.FAILED
        output = ""
        expired = False
        try:
            r = subprocess.run(
                cmd,
                shell=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                timeout=test.timeout(),
            )
            output = r.stdout
        except subprocess.TimeoutExpired as ex:
            output = ex.stdout
            expired = True

        logging.debug("%s", output.decode("utf-8", errors="replace"))

        if expired:
            logging.debug("Test failed: took longer than %ds.", test.timeout())
            r = subprocess.run(
                "docker compose --env-file empty.env stop " + containers,
                shell=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                timeout=60,
            )
            logging.debug("%s", r.stdout.decode("utf-8", errors="replace"))

        # copy the pcaps from the simulator
        self._copy_logs("sim", sim_log_dir)
        self._copy_logs("client", client_log_dir)
        self._copy_logs("server", server_log_dir)

        if not expired:
            lines = output.splitlines()
            if self._is_unsupported(lines):
                status = TestResult.UNSUPPORTED
            elif any("client exited with code 0" in str(line) for line in lines):
                try:
                    status = test.check()
                except FileNotFoundError as e:
                    logging.error(f"testcase.check() threw FileNotFoundError: {e}")
                    status = TestResult.FAILED

        # save logs
        logging.getLogger().removeHandler(log_handler)
        log_handler.close()
        if status == TestResult.FAILED or status == TestResult.SUCCEEDED:
            log_dir = self._log_dir + "/" + server + "_" + client + "/" + str(test)
            if log_dir_prefix:
                log_dir += "/" + log_dir_prefix
            shutil.copytree(server_log_dir.name, log_dir + "/server")
            shutil.copytree(client_log_dir.name, log_dir + "/client")
            shutil.copytree(sim_log_dir.name, log_dir + "/sim")
            shutil.copyfile(log_file.name, log_dir + "/output.txt")
            if self._save_files and status == TestResult.FAILED:
                shutil.copytree(test.www_dir(), log_dir + "/www")
                try:
                    shutil.copytree(test.download_dir(), log_dir + "/downloads")
                except Exception as exception:
                    logging.info("Could not copy downloaded files: %s", exception)

        test.cleanup()
        server_log_dir.cleanup()
        client_log_dir.cleanup()
        sim_log_dir.cleanup()
        logging.debug(
            "Test: %s took %ss, status: %s",
            str(test),
            (datetime.now() - start_time).total_seconds(),
            str(status),
        )

        # measurements also have a value
        if hasattr(test, "result"):
            value = test.result()
        else:
            value = None

        return status, value

    def _run_measurement(
        self, server: str, client: str, test: Callable[[], testcases_quic.Measurement]
    ) -> MeasurementResult:
        values = []
        for i in range(0, test.repetitions()):
            result, value = self._run_test(server, client, "%d" % (i + 1), test)
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
            if not (
                self._check_impl_is_compliant(server, Perspective.SERVER)
                and self._check_impl_is_compliant(client, Perspective.CLIENT)
            ):
                logging.info("Not compliant, skipping")
                continue

            # run the test cases
            for testcase in self._tests:
                status = self._run_testcase(server, client, testcase)
                self.test_results[server][client][testcase] = status
                if status == TestResult.FAILED:
                    nr_failed += 1

            # run the measurements
            for measurement in self._measurements:
                res = self._run_measurement(server, client, measurement)
                self.measurement_results[server][client][measurement] = res

        self._postprocess_results()
        self._print_results()
        self._export_results()
        return nr_failed
