import json, os, random, shutil, subprocess, string, logging, statistics, tempfile, time, re
from typing import Callable, List
from termcolor import colored
from enum import Enum
import prettytable

import testcases


def random_string(length: int):
  """ Generate a random string of fixed length """
  letters = string.ascii_lowercase
  return ''.join(random.choice(letters) for i in range(length))

class TestResult(Enum):
  SUCCEEDED = "succeeded"
  FAILED = "failed"
  UNSUPPORTED = "unsupported"

class MeasurementResult:
  result = TestResult
  details = str

class LogFileFormatter(logging.Formatter):
  def format(self, record):
    msg = super(LogFileFormatter, self).format(record)
    # remove color control characters
    return re.compile(r'\x1B[@-_][0-?]*[ -/]*[@-~]').sub('', msg)

class InteropRunner:
  test_results = {}
  measurement_results = {}
  compliant = {}
  _implementations = {}
  _servers = []
  _clients = []
  _tests = []
  _measurements = []
  _output = ""

  def __init__(self, implementations: dict, servers: List[str], clients: List[str], tests: List[testcases.TestCase], measurements: List[testcases.Measurement], output: str):
    self._tests = tests
    self._measurements = measurements
    self._servers = servers
    self._clients = clients
    self._implementations = implementations
    self._output = output
    for server in servers:
      self.test_results[server] = {}
      self.measurement_results[server] = {}
      for client in clients:
        self.test_results[server][client] = {}
        for test in self._tests:
          self.test_results[server][client][test] = {}
        self.measurement_results[server][client] = {}
        for measurement in measurements:
          self.measurement_results[server][client][measurement] = {}

  def _is_unsupported(self, lines: List[str]) -> bool:
    return any("exited with code 127" in str(l) for l in lines) or any("exit status 127" in str(l) for l in lines)

  def _check_impl_is_compliant(self, name: str) -> bool:
    """ check if an implementation return UNSUPPORTED for unknown test cases """
    if name in self.compliant:
      logging.debug("%s already tested for compliance: %s", name, str(self.compliant))
      return self.compliant[name]

    client_log_dir = tempfile.TemporaryDirectory(dir="/tmp", prefix="logs_client_")
    www_dir = tempfile.TemporaryDirectory(dir="/tmp", prefix="compliance_www_")
    downloads_dir = tempfile.TemporaryDirectory(dir="/tmp", prefix="compliance_downloads_")

    # check that the client is capable of returning UNSUPPORTED
    logging.debug("Checking compliance of %s client", name)
    cmd = (
        "TESTCASE=" + random_string(6) + " "
        "SERVER_LOGS=/dev/null "
        "CLIENT_LOGS=" + client_log_dir.name + " "
        "WWW=" + www_dir.name + " "
        "DOWNLOADS=" + downloads_dir.name + " "
        "SCENARIO=\"simple-p2p --delay=15ms --bandwidth=10Mbps --queue=25\" "
        "CLIENT=" + self._implementations[name] + " "
        "docker-compose up --timeout 0 --abort-on-container-exit sim client"
      )
    output = subprocess.run(cmd, shell=True, stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
    if not self._is_unsupported(output.stdout.splitlines()):
      logging.error("%s client not compliant.", name)
      logging.debug("%s", output.stdout.decode('utf-8'))
      self.compliant[name] = False
      return False
    logging.debug("%s client compliant.", name)

    # check that the server is capable of returning UNSUPPORTED
    logging.debug("Checking compliance of %s server", name)
    server_log_dir = tempfile.TemporaryDirectory(dir="/tmp", prefix="logs_server_")
    cmd = (
        "TESTCASE=" + random_string(6) + " "
        "SERVER_LOGS=" + server_log_dir.name + " "
        "CLIENT_LOGS=/dev/null "
        "WWW=" + www_dir.name + " "
        "DOWNLOADS=" + downloads_dir.name + " "
        "SERVER=" + self._implementations[name] + " "
        "docker-compose up server"
      )
    output = subprocess.run(cmd, shell=True, stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
    if not self._is_unsupported(output.stdout.splitlines()):
      logging.error("%s server not compliant.", name)
      logging.debug("%s", output.stdout.decode('utf-8'))
      self.compliant[name] = False
      return False
    logging.info("%s server compliant.", name)
    
    # remember compliance test outcome
    self.compliant[name] = True
    return True


  def _print_results(self):
    """print the interop table"""
    def get_letters(result):
      return "".join([ test.abbreviation() for test in cell if cell[test] is result ])
    
    if len(self._tests) > 0:
      t = prettytable.PrettyTable()
      t.hrules = prettytable.ALL
      t.vrules = prettytable.ALL
      t.field_names = [ "" ] + [ name for name in self._servers ]
      for client in self._clients:
        row = [ client ]
        for server in self._servers:
          cell = self.test_results[server][client]
          res = colored(get_letters(TestResult.SUCCEEDED), "green") + "\n"
          res += colored(get_letters(TestResult.UNSUPPORTED), "yellow") + "\n"
          res += colored(get_letters(TestResult.FAILED), "red")
          row += [ res ]
        t.add_row(row)
      print(t)
    
    if len(self._measurements) > 0:
      t = prettytable.PrettyTable()
      t.hrules = prettytable.ALL
      t.vrules = prettytable.ALL
      t.field_names = [ "" ] + [ name for name in self._servers ]
      for client in self._clients:
        row = [ client ]
        for server in self._servers:
          cell = self.measurement_results[server][client]
          results = []
          for measurement in self._measurements:
            res = cell[measurement]
            if res.result == TestResult.SUCCEEDED:
              results.append(colored(measurement.abbreviation() + ": " + res.details, "green"))
            elif res.result == TestResult.UNSUPPORTED:
              results.append(colored(measurement.abbreviation(), "yellow"))
            elif res.result == TestResult.FAILED:
              results.append(colored(measurement.abbreviation(), "yellow"))
          row += [ "\n".join(results) ]
        t.add_row(row)
      print(t)

  def _export_results(self):
    if not self._output:
      return

    out = {
      "timestamp": time.time(),
      "servers": [ name for name in self._servers ],
      "clients": [ name for name in self._clients ],
      "results": [],
      "measurements": [],
    }
      
    for client in self._clients:
      for server in self._servers:
        results = []
        for test in self._tests:
          results.append({
            "abbr": test.abbreviation(),
            "name": test.name(),
            "result": self.test_results[server][client][test].value,
          })
        out["results"].append(results)
       
        measurements = []
        for measurement in self._measurements:
          res = self.measurement_results[server][client][measurement]
          measurements.append({
            "name": measurement.name(),
            "abbr": measurement.abbreviation(),
            "result": res.result.value,
            "details": res.details,
          })
        out["measurements"].append(measurements)

    f = open(self._output, "w")
    json.dump(out, f)
    f.close()

  def _run_testcase(self, server: str, client: str, test: Callable[[], testcases.TestCase]) -> TestResult:
    sim_log_dir = tempfile.TemporaryDirectory(dir="/tmp", prefix="logs_sim_")
    testcase = test(sim_log_dir=sim_log_dir)
    return self._run_test(server, client, sim_log_dir, None, testcase)

  def _run_test(self, server: str, client: str, sim_log_dir: tempfile.TemporaryDirectory, log_dir_prefix: None, testcase: testcases.TestCase):
    print("Server: " + server + ". Client: " + client + ". Running test case: " + str(testcase))
    server_log_dir = tempfile.TemporaryDirectory(dir="/tmp", prefix="logs_server_")
    client_log_dir = tempfile.TemporaryDirectory(dir="/tmp", prefix="logs_client_")
    log_file = tempfile.NamedTemporaryFile(dir="/tmp", prefix="output_log_")
    log_handler = logging.FileHandler(log_file.name)
    log_handler.setLevel(logging.DEBUG)

    formatter = LogFileFormatter('%(asctime)s %(message)s')
    log_handler.setFormatter(formatter)
    logging.getLogger().addHandler(log_handler)

    reqs = " ".join(["https://server:443/" + p for p in testcase.get_paths()])
    logging.debug("Requests: %s", reqs)
    cmd = (
      "TESTCASE=" + testcase.testname() + " "
      "WWW=" + testcase.www_dir() + " "
      "DOWNLOADS=" + testcase.download_dir() + " "
      "SERVER_LOGS=" + server_log_dir.name + " "
      "CLIENT_LOGS=" + client_log_dir.name + " "
      "SCENARIO=\"simple-p2p --delay=15ms --bandwidth=10Mbps --queue=25\" "
      "CLIENT=" + self._implementations[client] + " "
      "SERVER=" + self._implementations[server] + " "
      "REQUESTS=\"" + reqs + "\" "
      "docker-compose up --abort-on-container-exit --timeout 1"
    )

    status = TestResult.FAILED
    output = ""
    expired = False
    try:
      r = subprocess.run(cmd, shell=True, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, timeout=60)
      output = r.stdout
    except subprocess.TimeoutExpired as ex:
      output = ex.stdout
      expired = True

    logging.debug("%s", output.decode('utf-8'))

    if expired:
      logging.debug("Test failed: took longer than 60s.")

    # copy the pcaps from the simulator
    subprocess.run(
      "docker cp \"$(docker-compose --log-level ERROR ps -q sim)\":/logs/. " + sim_log_dir.name,
      shell=True, stdout=subprocess.PIPE, stderr=subprocess.STDOUT
    )
    # copy logs from the client
    subprocess.run(
      "docker cp \"$(docker-compose --log-level ERROR ps -q client)\":/logs/. " + client_log_dir.name,
      shell=True, stdout=subprocess.PIPE, stderr=subprocess.STDOUT
    )
    # copy logs from the server
    subprocess.run(
      "docker cp \"$(docker-compose --log-level ERROR ps -q server)\":/logs/. " + server_log_dir.name,
      shell=True, stdout=subprocess.PIPE, stderr=subprocess.STDOUT
    )

    if not expired:
      lines = output.splitlines()
      if self._is_unsupported(lines):
        status = TestResult.UNSUPPORTED
      elif any("client exited with code 0" in str(l) for l in lines):
        if testcase.check():
          status = TestResult.SUCCEEDED

    # save logs
    logging.getLogger().removeHandler(log_handler)
    log_handler.close()
    if status == TestResult.FAILED or status == TestResult.SUCCEEDED:
      log_dir = "logs/" + server + "_" + client + "/" + str(testcase)
      if log_dir_prefix:
        log_dir += "/" + log_dir_prefix
      shutil.copytree(server_log_dir.name, log_dir + "/server")
      shutil.copytree(client_log_dir.name, log_dir + "/client")
      shutil.copytree(sim_log_dir.name, log_dir + "/sim")
      shutil.copyfile(log_file.name, log_dir + "/output.txt")
      if status == TestResult.FAILED:
        shutil.copytree(testcase.www_dir(), log_dir + "/www")
        try:
          shutil.copytree(testcase.download_dir(), log_dir + "/downloads")
        except Exception as exception:
          logging.info("Could not copy downloaded files: %s", exception)

    testcase.cleanup()
    server_log_dir.cleanup()
    client_log_dir.cleanup()
    sim_log_dir.cleanup()
    return status

  def _run_measurement(self, server: str, client: str, test: Callable[[], testcases.Measurement]) -> MeasurementResult:
    values = []
    for i in range (0, test.repetitions()):
      sim_log_dir = tempfile.TemporaryDirectory(dir="/tmp", prefix="logs_sim_")
      testcase = test(sim_log_dir=sim_log_dir)
      result = self._run_test(server, client, sim_log_dir, "%d" % (i+1), testcase)
      if result != TestResult.SUCCEEDED:
        res = MeasurementResult()
        res.result = result
        res.details = ""
        return res
      values.append(testcase.result())

    logging.debug(values)    
    res = MeasurementResult()
    res.result = TestResult.SUCCEEDED
    res.details = "{:.0f} (± {:.0f}) {}".format(statistics.mean(values), statistics.stdev(values), test.unit())
    return res

  def run(self):
    """run the interop test suite and output the table"""

    # clear the logs directory
    if os.path.exists("logs/"):
      shutil.rmtree("logs/")
    
    for server in self._servers:
      for client in self._clients:
        logging.info("Running with server %s (%s) and client %s (%s)", server, self._implementations[server], client, self._implementations[client])
        if not (self._check_impl_is_compliant(server) and self._check_impl_is_compliant(client)):
          logging.info("Not compliant, skipping")
          continue

        # run the test cases
        for testcase in self._tests:
          status = self._run_testcase(server, client, testcase)
          self.test_results[server][client][testcase] = status

        # run the measurements
        for measurement in self._measurements:
          res = self._run_measurement(server, client, measurement)
          self.measurement_results[server][client][measurement] = res

    self._print_results()
    self._export_results()
