import json
import logging
import os
import random
import re
import shutil
import statistics
import string
import subprocess
import sys
import tempfile
from datetime import datetime
from typing import Callable, List, Tuple

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
        tests: List[testcases.TestCase],
        measurements: List[testcases.Measurement],
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
            # Use a Windows-safe timestamp (no colons)
            safe_time = self._start_time.strftime("%Y-%m-%dT%H-%M-%S")
            self._log_dir = f"logs_{safe_time}"
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

    def _check_impl_is_compliant(self, name: str) -> bool:
        """check if an implementation return UNSUPPORTED for unknown test cases"""
        if name in self.compliant:
            logging.debug(
                "%s already tested for compliance: %s", name, str(self.compliant)
            )
            return self.compliant[name]

        tempdir = tempfile.gettempdir()
        client_log_dir = tempfile.TemporaryDirectory(dir=tempdir, prefix="logs_client_")
        www_dir = tempfile.TemporaryDirectory(dir=tempdir, prefix="compliance_www_")
        certs_dir = tempfile.TemporaryDirectory(dir=tempdir, prefix="compliance_certs_")
        downloads_dir = tempfile.TemporaryDirectory(
            dir=tempdir, prefix="compliance_downloads_"
        )

        testcases.generate_cert_chain(certs_dir.name)

        # check that the client is capable of returning UNSUPPORTED
        logging.debug("Checking compliance of %s client", name)
        env_vars = {
            "CERTS": certs_dir.name,
            "TESTCASE_CLIENT": random_string(6),
            "SERVER_LOGS": "/dev/null",
            "CLIENT_LOGS": client_log_dir.name,
            "WWW": www_dir.name,
            "DOWNLOADS": downloads_dir.name,
            "SCENARIO": "simple-p2p --delay=15ms --bandwidth=10Mbps --queue=25",
            "CLIENT": self._implementations[name]["image"],
            "SERVER": self._implementations[name]["image"],
        }
        if os.name == "nt":
            cmd = "".join([f"set {k}={v}&& " for k, v in env_vars.items()])
            cmd += "docker compose --env-file empty.env up --timeout 0 --abort-on-container-exit -V sim client"
        else:
            cmd = " ".join([f"{k}='{v}'" for k, v in env_vars.items()])
            cmd += " docker compose --env-file empty.env up --timeout 0 --abort-on-container-exit -V sim client"
        output = subprocess.run(
            cmd, shell=True, stdout=subprocess.PIPE, stderr=subprocess.STDOUT
        )
        if not self._is_unsupported(output.stdout.splitlines()):
            logging.error("%s client not compliant.", name)
            logging.debug("%s", output.stdout.decode("utf-8", errors="replace"))
            self.compliant[name] = False
            return False
        logging.debug("%s client compliant.", name)

        # check that the server is capable of returning UNSUPPORTED
        logging.debug("Checking compliance of %s server", name)
        server_log_dir = tempfile.TemporaryDirectory(dir=tempdir, prefix="logs_server_")
        env_vars = {
            "CERTS": certs_dir.name,
            "TESTCASE_SERVER": random_string(6),
            "SERVER_LOGS": server_log_dir.name,
            "CLIENT_LOGS": "/dev/null",
            "WWW": www_dir.name,
            "DOWNLOADS": downloads_dir.name,
            "CLIENT": self._implementations[name]["image"],
            "SERVER": self._implementations[name]["image"],
        }
        if os.name == "nt":
            cmd = "".join([f"set {k}={v}&& " for k, v in env_vars.items()])
            cmd += "docker compose --env-file empty.env up -V server"
        else:
            cmd = " ".join([f"{k}='{v}'" for k, v in env_vars.items()])
            cmd += " docker compose --env-file empty.env up -V server"
        output = subprocess.run(
            cmd, shell=True, stdout=subprocess.PIPE, stderr=subprocess.STDOUT
        )
        if not self._is_unsupported(output.stdout.splitlines()):
            logging.error("%s server not compliant.", name)
            logging.debug("%s", output.stdout.decode("utf-8", errors="replace"))
            self.compliant[name] = False
            return False
        logging.debug("%s server compliant.", name)

        # remember compliance test outcome
        self.compliant[name] = True
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

        f = open(self._output, "w")
        json.dump(out, f)
        f.close()

    def _copy_logs(self, container: str, dir: tempfile.TemporaryDirectory):
        # Find container ID by name using docker ps --format
        try:
            ps = subprocess.run(
                ["docker", "ps", "-a", "--format", "{{.ID}} {{.Names}}"],
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                encoding="utf-8",
                check=True,
            )
            container_id = None
            for line in ps.stdout.splitlines():
                parts = line.strip().split(None, 1)
                if len(parts) == 2 and parts[1] == container:
                    container_id = parts[0]
                    break
            if not container_id:
                logging.info(f"Could not find container ID for {container}")
                return
            cp = subprocess.run(
                ["docker", "cp", f"{container_id}:/logs/.", dir.name],
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                encoding="utf-8",
            )
            if cp.returncode != 0:
                logging.info(
                    f"Copying logs from {container} failed: {cp.stdout}"
                )
        except Exception as e:
            logging.info(f"Exception copying logs from {container}: {e}")

    def _run_testcase(
        self, server: str, client: str, test: Callable[[], testcases.TestCase]
    ) -> TestResult:
    # Print test case names for debugging at the very start
        testcase_obj = test()
        print(f"[DEBUG] TESTCASE_SERVER: {testcase_obj.testname(Perspective.SERVER)}")
        print(f"[DEBUG] TESTCASE_CLIENT: {testcase_obj.testname(Perspective.CLIENT)}")
        return self._run_test(server, client, None, test)[0]
    def _run_test(
        self,
        server: str,
        client: str,
        log_dir_prefix: None,
        test: Callable[[], testcases.TestCase],
    ) -> Tuple[TestResult, float]:
        print("[DEBUG] Entered _run_test() in interop.py")
        start_time = datetime.now()
        tempdir = tempfile.gettempdir()
        # Use the logs_dir set on the testcase if present, else create new temp dirs
        testcase = test()
        logs_dir = getattr(testcase, '_logs_dir', None)
        if logs_dir is not None:
            sim_log_dir = logs_dir
            server_log_dir = logs_dir
            client_log_dir = logs_dir
        else:
            sim_log_dir = tempfile.TemporaryDirectory(dir=tempdir, prefix="logs_sim_")
            server_log_dir = tempfile.TemporaryDirectory(dir=tempdir, prefix="logs_server_")
            client_log_dir = tempfile.TemporaryDirectory(dir=tempdir, prefix="logs_client_")
        log_fd, log_path = tempfile.mkstemp(dir=tempdir, prefix="output_log_")
        import os
        os.close(log_fd)
        log_handler = logging.FileHandler(log_path)
        log_handler.setLevel(logging.DEBUG)

        formatter = LogFileFormatter("%(asctime)s %(message)s")
        log_handler.setFormatter(formatter)
        logging.getLogger().addHandler(log_handler)
        certs_dir = testcase.certs_dir()
        # Always look for cert.pem inside the certs subdirectory
        if not certs_dir.rstrip('/\\').endswith('certs'):
            certs_dir = os.path.join(certs_dir, 'certs')
        cert_pem_path = os.path.join(certs_dir, 'cert.pem')
        # Print certs directory and contents for debugging
        print(f"[DEBUG] Using certs directory: {certs_dir}")
        try:
            print("[DEBUG] certs directory contents:", os.listdir(certs_dir))
        except Exception as e:
            print(f"[DEBUG] Could not list certs directory: {e}")
        if not os.path.isfile(cert_pem_path):
            logging.error(f"cert.pem not found at {cert_pem_path}. Aborting test.")
            print(f"ERROR: cert.pem not found at {cert_pem_path}. Skipping test.")
            return TestResult.FAILED, 0.0

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
        # Use requests.env if it exists and this is the manyfiles test, else use empty.env
        requests_env_path = os.path.join(os.path.dirname(__file__), 'requests.env')
        if os.path.exists(requests_env_path) and getattr(testcase, 'name', lambda: None)() == 'manyfiles':
            env_file = 'requests.env'
        else:
            env_file = 'empty.env'

        # Write all test-related env vars to the env file
        # Always use the certs subdirectory for CERTS and volume mapping
        certs_dir = testcase.certs_dir()
        if not certs_dir.rstrip('/\\').endswith('certs'):
            certs_dir = os.path.join(certs_dir, 'certs')
        # Normalize Windows path for Docker volume mount
        def normalize_docker_path(path):
            if os.name == 'nt':
                # Convert C:\path\to\dir to /c/path/to/dir
                drive, rest = os.path.splitdrive(path)
                if drive:
                    drive_letter = drive.rstrip(':').lower()
                    rest = rest.replace('\\', '/').replace('//', '/')
                    if not rest.startswith('/'):
                        rest = '/' + rest
                    return f'/{drive_letter}{rest}'
                else:
                    return path.replace('\\', '/')
            else:
                return path
        certs_dir_docker = normalize_docker_path(certs_dir)
        www_dir_docker = normalize_docker_path(testcase.www_dir())
        downloads_dir_docker = normalize_docker_path(testcase.download_dir())
        # Print the host certs_dir and intended container mapping for debugging
        print(f"[DEBUG] Host certs_dir: {certs_dir}")
        print(f"[DEBUG] Docker Compose will map this to /certs inside the container (host: {certs_dir_docker})")
        print(f"[DEBUG] Host www_dir: {testcase.www_dir()}")
        print(f"[DEBUG] Docker Compose will map this to /www inside the container (host: {www_dir_docker})")
        print(f"[DEBUG] Host downloads_dir: {testcase.download_dir()}")
        print(f"[DEBUG] Docker Compose will map this to /downloads inside the container (host: {downloads_dir_docker})")
        env_vars = {
            "WAITFORSERVER": "server:443",
            # Only use the normalized Docker path for CERTS, WWW, DOWNLOADS
            "CERTS": certs_dir_docker,
            "TESTCASE_SERVER": testcase.testname(Perspective.SERVER),
            "TESTCASE_CLIENT": testcase.testname(Perspective.CLIENT),
            "WWW": www_dir_docker,
            "DOWNLOADS": downloads_dir_docker,
            "SERVER_LOGS": server_log_dir.name,
            "CLIENT_LOGS": client_log_dir.name,
            "SCENARIO": testcase.scenario(),
            "CLIENT": self._implementations[client]["image"],
            "SERVER": self._implementations[server]["image"],
        }
        print(f"[DEBUG] TESTCASE_SERVER: {env_vars['TESTCASE_SERVER']}")
        print(f"[DEBUG] TESTCASE_CLIENT: {env_vars['TESTCASE_CLIENT']}")
        # Add REQUESTS if not using requests.env
        if env_file != 'requests.env':
            env_vars["REQUESTS"] = reqs
        # Add any additional envs from the testcase
        for extra in testcase.additional_envs():
            if extra.strip():
                k, _, v = extra.partition('=')
                env_vars[k.strip()] = v.strip()
        # Write env file
        env_file_path = os.path.join(os.path.dirname(__file__), env_file)
        with open(env_file_path, 'w', encoding='utf-8') as f:
            for k, v in env_vars.items():
                f.write(f'{k}="{v}"')

        containers = "sim client server " + " ".join(testcase.additional_containers())
        cmd = f"docker compose --env-file {env_file} up --abort-on-container-exit --timeout 1 {containers}"
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
                timeout=testcase.timeout(),
            )
            output = r.stdout
        except subprocess.TimeoutExpired as ex:
            output = ex.stdout
            expired = True

        logging.debug("%s", output.decode("utf-8", errors="replace"))

        if expired:
            logging.debug("Test failed: took longer than %ds.", testcase.timeout())
            r = subprocess.run(
                "docker compose --env-file empty.env stop " + containers,
                shell=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                timeout=60,
            )
            logging.debug("%s", r.stdout.decode("utf-8", errors="replace"))

        # copy the pcaps from the simulator BEFORE calling testcase.check()
        self._copy_logs("sim", sim_log_dir)
        import os
        try:
            print(f"[DEBUG] Contents of sim_log_dir ({sim_log_dir.name}): {os.listdir(sim_log_dir.name)}")
        except Exception as e:
            print(f"[DEBUG] Could not list sim_log_dir: {e}")
        self._copy_logs("client", client_log_dir)
        self._copy_logs("server", server_log_dir)

        if not expired:
            lines = output.splitlines()
            if self._is_unsupported(lines):
                status = TestResult.UNSUPPORTED
            elif any("client exited with code 0" in str(line) for line in lines):
                try:
                    status = testcase.check()
                except FileNotFoundError as e:
                    logging.error(f"testcase.check() threw FileNotFoundError: {e}")
                    status = TestResult.FAILED

        # save logs
        logging.getLogger().removeHandler(log_handler)
        log_handler.close()
        if status == TestResult.FAILED or status == TestResult.SUCCEEDED:
            log_dir = self._log_dir + "/" + server + "_" + client + "/" + str(testcase)
            if log_dir_prefix:
                log_dir += "/" + log_dir_prefix
            shutil.copytree(server_log_dir.name, log_dir + "/server")
            shutil.copytree(client_log_dir.name, log_dir + "/client")
            shutil.copytree(sim_log_dir.name, log_dir + "/sim")
            shutil.copyfile(log_path, log_dir + "/output.txt")
            if self._save_files and status == TestResult.FAILED:
                shutil.copytree(testcase.www_dir(), log_dir + "/www")
                try:
                    shutil.copytree(testcase.download_dir(), log_dir + "/downloads")
                except Exception as exception:
                    logging.info("Could not copy downloaded files: %s", exception)

        testcase.cleanup()
        # Only clean up temp dirs if we created them here
        if logs_dir is None:
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
        self, server: str, client: str, measurement_class, test_factory: Callable[[], testcases.Measurement]
    ) -> MeasurementResult:
        values = []
        for i in range(0, measurement_class.repetitions()):
            measurement_obj = test_factory()
            result, value = self._run_test(server, client, "%d" % (i + 1), lambda: measurement_obj)
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
            statistics.mean(values), statistics.stdev(values), measurement_class.unit()
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
            # Bypass compliance check for debugging: always run tests
            # if not (
            #     self._check_impl_is_compliant(server)
            #     and self._check_impl_is_compliant(client)
            # ):
            #     logging.info("Not compliant, skipping")
            #     continue

            # run the test cases
            for testcase in self._tests:
                # Prepare arguments for test case instantiation
                tempdir = tempfile.gettempdir()
                # Create a single logs_dir for this test and set it on the testcase
                logs_dir = tempfile.TemporaryDirectory(dir=tempdir, prefix="logs_sim_")
                client_log_dir = logs_dir
                server_log_dir = logs_dir
                sim_log_dir = logs_dir
                testcase_obj = testcase(
                    sim_log_dir=sim_log_dir,
                    client_keylog_file=client_log_dir.name + "/keys.log",
                    server_keylog_file=server_log_dir.name + "/keys.log",
                )
                # Set temp dirs for www, downloads, certs, and logs on the testcase object
                testcase_obj._www_dir = www_dir = tempfile.TemporaryDirectory(dir=tempdir, prefix="www_")
                testcase_obj._download_dir = download_dir = tempfile.TemporaryDirectory(dir=tempdir, prefix="download_")
                cert_dir = tempfile.TemporaryDirectory(dir=tempdir, prefix="certs_")
                from testcases import generate_cert_chain
                generate_cert_chain(cert_dir.name)
                testcase_obj._cert_dir = cert_dir
                testcase_obj._logs_dir = logs_dir
                print(f"[DEBUG] TESTCASE_SERVER: {testcase_obj.testname(Perspective.SERVER)}")
                print(f"[DEBUG] TESTCASE_CLIENT: {testcase_obj.testname(Perspective.CLIENT)}")
                # Pass the test case object directly to _run_testcase
                status = self._run_testcase(server, client, lambda: testcase_obj)
                self.test_results[server][client][testcase] = status
                if status == TestResult.FAILED:
                    nr_failed += 1
                # Clean up temp dirs after test run
                logs_dir.cleanup()
                www_dir.cleanup()
                download_dir.cleanup()
                cert_dir.cleanup()

            # run the measurements
            for measurement in self._measurements:
                def measurement_factory():
                    sim_log_dir = tempfile.TemporaryDirectory(dir=tempdir, prefix="logs_sim_")
                    client_log_dir = tempfile.TemporaryDirectory(dir=tempdir, prefix="logs_client_")
                    server_log_dir = tempfile.TemporaryDirectory(dir=tempdir, prefix="logs_server_")
                    www_dir = tempfile.TemporaryDirectory(dir=tempdir, prefix="www_")
                    download_dir = tempfile.TemporaryDirectory(dir=tempdir, prefix="download_")
                    cert_dir = tempfile.TemporaryDirectory(dir=tempdir, prefix="certs_")
                    from testcases import generate_cert_chain
                    generate_cert_chain(cert_dir.name)
                    measurement_obj = measurement(
                        sim_log_dir=sim_log_dir,
                        client_keylog_file=client_log_dir.name + "/keys.log",
                        server_keylog_file=server_log_dir.name + "/keys.log",
                    )
                    measurement_obj._www_dir = www_dir
                    measurement_obj._download_dir = download_dir
                    measurement_obj._cert_dir = cert_dir
                    measurement_obj._temp_dirs = [sim_log_dir, client_log_dir, server_log_dir, www_dir, download_dir, cert_dir]
                    return measurement_obj
                res = self._run_measurement(server, client, measurement, measurement_factory)
                self.measurement_results[server][client][measurement] = res
                # Clean up temp dirs after measurement run
                for d in getattr(res, '_temp_dirs', []):
                    d.cleanup()

        self._postprocess_results()
        self._print_results()
        self._export_results()
        return nr_failed
