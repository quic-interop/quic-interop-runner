import abc, filecmp, os, string, tempfile, random, logging, sys
from Crypto.Cipher import AES
from datetime import timedelta

from trace import TraceAnalyzer, Direction

KB = 1<<10
MB = 1<<20

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
    tr = TraceAnalyzer(self._sim_log_dir.name + "/trace_node_left.pcap")
    cap = tr.get_retry()
    sent = True
    try: 
      cap.next()
    except StopIteration:
      sent = False
    cap.close()
    return sent

  def _check_files(self):
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
        logging.info("Could not compoare files %s and %s: %s", self.www_dir() + f, fp, exception)
        return False
    logging.debug("Check of downloaded files succeeded.")
    return True

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
    cap_initial = tr.get_initial(Direction.FROM_CLIENT)
    dcid = ""
    for p in cap_initial:
      dcid = p.quic.dcid
    cap_initial.close()
    if dcid is "":
      logging.info("Didn't find an Initial / a DCID.")
      return False
    cap_server = tr.get_vnp()
    conn_id_matches = False
    for p in cap_server:
      if p.quic.scid == dcid:
        conn_id_matches = True
    cap_server.close()
    if not conn_id_matches:
      logging.info("Didn't find a Version Negotiation Packet with matching SCID.")
    return conn_id_matches

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
    if not self._check_files():
      return False
    if self._retry_sent():
      logging.info("Didn't expect a Retry to be sent.")
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
    return self._check_files()

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
    cap_retry = tr.get_retry(Direction.FROM_SERVER)
    for p in cap_retry:
      tokens += [ p.quic.retry_token.replace(":", "") ]
    cap_retry.close()
    if len(tokens) == 0:
      logging.info("Didn't find any Retry packets.")
      return False
    
    # check that an Initial packet uses a token sent in the Retry packet(s)
    cap_initial = tr.get_initial(Direction.FROM_CLIENT)
    found = False
    for p in cap_initial:
      if p.quic.long_packet_type != "0" or p.quic.token_length == "0":
        continue
      token = p.quic.token.replace(":", "")
      if token in tokens:
        logging.debug("Check of Retry succeeded. Token used: %s", token)
        found = True
        break
    cap_initial.close()
    if not found:
      logging.info("Didn't find any Initial packet using a Retry token.")
    return found

  def check(self) -> bool:
    if not self._check_files():
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
    return self._check_files()

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
    return self._check_files()

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
    c = self._check_files()
    print("check", c)
    return c

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
    if not self._check_files():
      return False
    cap = TraceAnalyzer(self._sim_log_dir.name + "/trace_node_left.pcap").get_1rtt(Direction.FROM_SERVER)

    first, last = 0, 0
    for p in cap:
      if (first == 0):
        first = p.sniff_time
      last = p.sniff_time
    cap.close()

    if (last - first == 0):
      return False
    time = (last - first) / timedelta(milliseconds = 1)
    goodput = (8 * self.FILESIZE) / time
    logging.debug("Transfering %d MB took %d ms. Goodput: %d kbps", self.FILESIZE/MB, time, goodput)
    self._result = goodput
    return True

  def result(self) -> float:
    return self._result

TESTCASES = [ 
  TestCaseHandshake,
  TestCaseTransfer,
  TestCaseRetry,
  TestCaseResumption,
  TestCaseHTTP3,
  TestCaseBlackhole,
]

MEASUREMENTS = [
  MeasurementGoodput,
]
