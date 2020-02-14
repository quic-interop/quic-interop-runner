import abc, filecmp, os, string, tempfile, random, logging, sys
from Crypto.Cipher import AES
from datetime import timedelta
from typing import List

from trace import TraceAnalyzer, Direction

KB = 1<<10
MB = 1<<20

QUIC_VERSION="0xff000019" # draft-25

def random_string(length: int):
  """Generate a random string of fixed length """
  letters = string.ascii_lowercase
  return ''.join(random.choice(letters) for i in range(length))

class TestCase(abc.ABC):
  _files = []
  _www_dir = None
  _download_dir = None
  _sim_log_dir = None

  def __init__(self, sim_log_dir: tempfile.TemporaryDirectory):
    self._files = []
    self._sim_log_dir = sim_log_dir

  @abc.abstractmethod
  def name(self):
    pass

  def __str__(self):
    return self.name()

  def testname(self):
    """ The name of testcase presented to the endpoint Docker images"""
    return self.name()

  @staticmethod
  def scenario() -> str:
    """ Scenario for the ns3 simulator """
    return "simple-p2p --delay=15ms --bandwidth=10Mbps --queue=25"

  @staticmethod
  def timeout() -> int:
    """ timeout in s """
    return 60

  @staticmethod
  def additional_envs() -> List[str]:
    return [ "" ]

  @staticmethod
  def additional_containers() -> List[str]:
    return [ "" ]

  def www_dir(self):
    if not self._www_dir:
      self._www_dir = tempfile.TemporaryDirectory(dir = "/tmp", prefix = "www_")
    return self._www_dir.name + "/"
  
  def download_dir(self):
    if not self._download_dir:
      self._download_dir = tempfile.TemporaryDirectory(dir = "/tmp", prefix = "download_")
    return self._download_dir.name + "/"

  # see https://www.stefanocappellini.it/generate-pseudorandom-bytes-with-python/ for benchmarks
  def _generate_random_file(self, size: int) -> str:
    filename = random_string(10)
    enc = AES.new(os.urandom(32), AES.MODE_OFB, b'a' * 16)
    f = open(self.www_dir() + filename, "wb")
    f.write(enc.encrypt(b' ' * size))
    f.close()
    logging.debug("Generated random file: %s of size: %d", filename, size)
    return filename

  def _retry_sent(self) -> bool:
    return len(TraceAnalyzer(self._sim_log_dir.name + "/trace_node_left.pcap").get_retry()) > 0

  def _check_version_and_files(self):
    versions = self._get_versions()
    if len(versions) != 1:
      logging.info("Expected exactly one version. Got %s", versions)
      return False
    if QUIC_VERSION not in versions:
      logging.info("Wrong version. Expected %s, got %s", QUIC_VERSION, versions)
      return False

    if len(self._files) == 0:
      raise Exception("No test files generated.")
    num_files = len([ n for n in os.listdir(self.download_dir()) if os.path.isfile(os.path.join(self.download_dir(), n)) ])
    if num_files != len(self._files):
      logging.info("Downloaded the wrong number of files. Got %d, expected %d.", num_files, len(self._files))
      return False
    for f in self._files:
      fp = self.download_dir() + f
      if not os.path.isfile(fp):
        logging.info("File %s does not exist.", fp)
        return False
      try:
        if not filecmp.cmp(self.www_dir() + f, fp, shallow=False):
          logging.info("File contents of %s do not match.", fp)
          return False
      except Exception as exception:
        logging.info("Could not compare files %s and %s: %s", self.www_dir() + f, fp, exception)
        return False
    logging.debug("Check of downloaded files succeeded.")
    return True

  def _count_handshakes(self) -> int:
    """ Count the number of QUIC handshakes """
    tr = TraceAnalyzer(self._sim_log_dir.name + "/trace_node_left.pcap")
    # Determine the number of handshakes by looking at Initial packets.
    # This is easier, since the SCID of Initial packets doesn't changes.
    return len(set([ p.scid for p in tr.get_initial(Direction.FROM_SERVER) ]))

  def _get_versions(self) -> set:
    """ Get the QUIC versions """
    tr = TraceAnalyzer(self._sim_log_dir.name + "/trace_node_left.pcap")
    return set([ p.version for p in tr.get_initial(Direction.FROM_SERVER) ])

  def cleanup(self):
    if self._www_dir:
      self._www_dir.cleanup()
      self._www_dir = None
    if self._download_dir:
      self._download_dir.cleanup()
      self._download_dir = None

  @abc.abstractmethod
  def get_paths(self):
    pass

  @abc.abstractmethod
  def check(self) -> bool:
    pass


class Measurement(TestCase):
  @abc.abstractmethod
  def result(self) -> str:
    pass

  @staticmethod
  @abc.abstractmethod
  def unit() -> str:
    pass

  @staticmethod
  @abc.abstractmethod
  def repetitions() -> int:
    pass


class TestCaseVersionNegotiation(TestCase):
  @staticmethod
  def name():
    return "versionnegotiation"
  
  @staticmethod
  def abbreviation():
    return "V"

  def get_paths(self):
    return [ "" ]
  
  def check(self):
    tr = TraceAnalyzer(self._sim_log_dir.name + "/trace_node_left.pcap")
    initials = tr.get_initial(Direction.FROM_CLIENT)
    dcid = ""
    for p in initials:
      dcid = p.dcid
      break
    if dcid is "":
      logging.info("Didn't find an Initial / a DCID.")
      return False
    vnps = tr.get_vnp()
    for p in vnps:
      if p.scid == dcid:
        return True
    logging.info("Didn't find a Version Negotiation Packet with matching SCID.")
    return False


class TestCaseHandshake(TestCase):
  @staticmethod
  def name():
    return "handshake"

  @staticmethod
  def abbreviation():
    return "H"

  def get_paths(self):
    self._files = [ self._generate_random_file(1*KB) ]
    return self._files

  def check(self):
    if not self._check_version_and_files():
      return False
    if self._retry_sent():
      logging.info("Didn't expect a Retry to be sent.")
      return False
    num_handshakes = self._count_handshakes()
    if num_handshakes != 1:
      logging.info("Expected exactly 1 handshake. Got: %d", num_handshakes)
      return False
    return True


class TestCaseTransfer(TestCase):
  @staticmethod
  def name():
    return "transfer"

  @staticmethod
  def abbreviation():
    return "DC"

  def get_paths(self):
    self._files = [ 
      self._generate_random_file(2*MB),
      self._generate_random_file(3*MB),
      self._generate_random_file(5*MB),
    ]
    return self._files

  def check(self):
    num_handshakes = self._count_handshakes()
    if num_handshakes != 1:
      logging.info("Expected exactly 1 handshake. Got: %d", num_handshakes)
      return False
    return self._check_version_and_files()


class TestCaseMultiplexing(TestCase):
  @staticmethod
  def name():
    return "multiplexing"

  @staticmethod
  def testname():
    return "transfer"

  @staticmethod
  def abbreviation():
    return "M"

  def get_paths(self):
    for _ in range(1, 2000):
      self._files.append(self._generate_random_file(32))
    return self._files

  def check(self):
    num_handshakes = self._count_handshakes()
    if num_handshakes != 1:
      logging.info("Expected exactly 1 handshake. Got: %d", num_handshakes)
      return False
    return self._check_version_and_files()


class TestCaseRetry(TestCase):
  @staticmethod
  def name():
    return "retry"

  @staticmethod
  def abbreviation():
    return "S"

  def get_paths(self):
    self._files = [ self._generate_random_file(10*KB), ]
    return self._files

  def _check_trace(self) -> bool:
    # check that (at least) one Retry packet was actually sent
    tr = TraceAnalyzer(self._sim_log_dir.name + "/trace_node_left.pcap")
    tokens = []
    retries = tr.get_retry(Direction.FROM_SERVER)
    for p in retries:
      tokens += [ p.retry_token.replace(":", "") ]
    if len(tokens) == 0:
      logging.info("Didn't find any Retry packets.")
      return False
    
    # check that an Initial packet uses a token sent in the Retry packet(s)
    initials = tr.get_initial(Direction.FROM_CLIENT)
    for p in initials:
      if p.token_length == "0":
        continue
      token = p.token.replace(":", "")
      if token in tokens:
        logging.debug("Check of Retry succeeded. Token used: %s", token)
        return True
    logging.info("Didn't find any Initial packet using a Retry token.")
    return False

  def check(self) -> bool:
    num_handshakes = self._count_handshakes()
    if num_handshakes != 1:
      logging.info("Expected exactly 1 handshake. Got: %d", num_handshakes)
      return False
    if not self._check_version_and_files():
      return False
    return self._check_trace()
    

class TestCaseResumption(TestCase):
  @staticmethod
  def name():
    return "resumption"

  @staticmethod
  def abbreviation():
    return "R"

  def get_paths(self):
    self._files = [ 
      self._generate_random_file(5*KB),
      self._generate_random_file(10*KB),
    ]
    return self._files

  def check(self):
    num_handshakes = self._count_handshakes()
    if num_handshakes != 2:
      logging.info("Expected exactly 2 handshake. Got: %d", num_handshakes)
      return False
    return self._check_version_and_files()


class TestCaseHTTP3(TestCase):
  @staticmethod
  def name():
    return "http3"

  @staticmethod
  def abbreviation():
    return "3"

  def get_paths(self):
    self._files = [ 
      self._generate_random_file(5*KB),
      self._generate_random_file(10*KB),
      self._generate_random_file(500*KB),
    ]
    return self._files

  def check(self):
    num_handshakes = self._count_handshakes()
    if num_handshakes != 1:
      logging.info("Expected exactly 1 handshake. Got: %d", num_handshakes)
      return False
    return self._check_version_and_files()


class TestCaseBlackhole(TestCase):
  @staticmethod
  def name():
    return "blackhole"

  @staticmethod
  def testname():
    return "transfer"

  @staticmethod
  def abbreviation():
    return "B"

  @staticmethod
  def scenario() -> str:
    """ Scenario for the ns3 simulator """
    return "blackhole --delay=15ms --bandwidth=10Mbps --queue=25 --on=5s --off=2s"

  def get_paths(self):
    self._files = [ self._generate_random_file(10*MB) ]
    return self._files

  def check(self):
    num_handshakes = self._count_handshakes()
    if num_handshakes != 1:
      logging.info("Expected exactly 1 handshake. Got: %d", num_handshakes)
      return False
    return self._check_version_and_files()


class TestCaseHandshakeLoss(TestCase):
  _num_runs = 50

  @staticmethod
  def name():
    return "handshakeloss"

  @staticmethod
  def testname():
    return "multiconnect"

  @staticmethod
  def abbreviation():
    return "L1"

  @staticmethod
  def timeout() -> int:
    return 300

  @staticmethod
  def scenario() -> str:
    """ Scenario for the ns3 simulator """
    return "drop-rate --delay=15ms --bandwidth=10Mbps --queue=25 --rate_to_server=30 --rate_to_client=30"

  def get_paths(self):
    for _ in range(self._num_runs):
      self._files.append(self._generate_random_file(1*KB))
    return self._files

  def check(self):
    num_handshakes = self._count_handshakes()
    if num_handshakes != self._num_runs:
      logging.info("Expected %d handshakes. Got: %d", self._num_runs, num_handshakes)
      return False
    return self._check_version_and_files()

class TestCaseTransferLoss(TestCase):
  @staticmethod
  def name():
    return "transferloss"

  @staticmethod
  def testname():
    return "transfer"

  @staticmethod
  def abbreviation():
    return "L2"

  @staticmethod
  def scenario() -> str:
    """ Scenario for the ns3 simulator """
    return "drop-rate --delay=15ms --bandwidth=10Mbps --queue=25 --rate_to_server=2 --rate_to_client=2"

  def get_paths(self):
    # At a packet loss rate of 2% and a MTU of 1500 bytes, we can expect 27 dropped packets.
    self._files = [ self._generate_random_file(2*MB) ]
    return self._files

  def check(self):
    num_handshakes = self._count_handshakes()
    if num_handshakes != 1:
      logging.info("Expected exactly 1 handshake. Got: %d", num_handshakes)
      return False
    return self._check_version_and_files()


class MeasurementGoodput(Measurement):
  FILESIZE = 10*MB
  _result = 0.0

  @staticmethod
  def name():
    return "goodput"

  @staticmethod
  def unit() -> str:
    return "kbps"

  @staticmethod
  def testname():
    return "transfer"

  @staticmethod
  def abbreviation():
    return "G"

  @staticmethod
  def repetitions() -> int:
    return 5

  def get_paths(self):
    self._files = [ self._generate_random_file(self.FILESIZE) ]
    return self._files

  def check(self) -> bool:
    num_handshakes = self._count_handshakes()
    if num_handshakes != 1:
      logging.info("Expected exactly 1 handshake. Got: %d", num_handshakes)
      return False
    if not self._check_version_and_files():
      return False

    packets = TraceAnalyzer(self._sim_log_dir.name + "/trace_node_left.pcap").get_1rtt(Direction.FROM_SERVER)
    first, last = 0, 0
    for p in packets:
      if (first == 0):
        first = p.sniff_time
      last = p.sniff_time

    if (last - first == 0):
      return False
    time = (last - first) / timedelta(milliseconds = 1)
    goodput = (8 * self.FILESIZE) / time
    logging.debug("Transfering %d MB took %d ms. Goodput: %d kbps", self.FILESIZE/MB, time, goodput)
    self._result = goodput
    return True

  def result(self) -> float:
    return self._result


class MeasurementCrossTraffic(MeasurementGoodput):
  FILESIZE=25*MB

  @staticmethod
  def name():
    return "crosstraffic"

  @staticmethod
  def abbreviation():
    return "C"

  @staticmethod
  def timeout() -> int:
    return 180
  
  @staticmethod
  def additional_envs() -> List[str]:
    return [ "IPERF_CONGESTION=cubic" ]

  @staticmethod
  def additional_containers() -> List[str]:
    return [ "iperf_server", "iperf_client" ]


TESTCASES = [ 
  TestCaseHandshake,
  TestCaseTransfer,
  TestCaseMultiplexing,
  TestCaseRetry,
  TestCaseResumption,
  TestCaseHTTP3,
  TestCaseBlackhole,
  TestCaseHandshakeLoss,
  TestCaseTransferLoss,
]

MEASUREMENTS = [
  MeasurementGoodput,
  MeasurementCrossTraffic,
]
