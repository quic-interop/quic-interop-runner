import abc
import filecmp
import logging
import os
import random
import string
import tempfile
from datetime import timedelta
from enum import Enum, IntEnum
from trace import Direction, TraceAnalyzer
from typing import List

from Crypto.Cipher import AES

from result import TestResult

KB = 1 << 10
MB = 1 << 20

QUIC_DRAFT = 29  # draft-29
QUIC_VERSION = hex(0xFF000000 + QUIC_DRAFT)


class Perspective(Enum):
    SERVER = "server"
    CLIENT = "client"


class ECN(IntEnum):
    NONE = 0
    ECT1 = 1
    ECT0 = 2
    CE = 3


def random_string(length: int):
    """Generate a random string of fixed length """
    letters = string.ascii_lowercase
    return "".join(random.choice(letters) for i in range(length))


class TestCase(abc.ABC):
    _files = []
    _www_dir = None
    _client_keylog_file = None
    _server_keylog_file = None
    _download_dir = None
    _sim_log_dir = None

    def __init__(
        self,
        sim_log_dir: tempfile.TemporaryDirectory,
        client_keylog_file: str,
        server_keylog_file: str,
    ):
        self._server_keylog_file = server_keylog_file
        self._client_keylog_file = client_keylog_file
        self._files = []
        self._sim_log_dir = sim_log_dir

    @abc.abstractmethod
    def name(self):
        pass

    @abc.abstractmethod
    def desc(self):
        pass

    def __str__(self):
        return self.name()

    def testname(self, p: Perspective):
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
        return [""]

    @staticmethod
    def additional_containers() -> List[str]:
        return [""]

    def www_dir(self):
        if not self._www_dir:
            self._www_dir = tempfile.TemporaryDirectory(dir="/tmp", prefix="www_")
        return self._www_dir.name + "/"

    def download_dir(self):
        if not self._download_dir:
            self._download_dir = tempfile.TemporaryDirectory(
                dir="/tmp", prefix="download_"
            )
        return self._download_dir.name + "/"

    def _keylog_file(self) -> str:
        if os.path.isfile(self._client_keylog_file):
            logging.debug("Using the client's key log file.")
            return self._client_keylog_file
        elif os.path.isfile(self._server_keylog_file):
            logging.debug("Using the server's key log file.")
            return self._server_keylog_file
        logging.debug("No key log file found.")

    def _client_trace(self):
        return TraceAnalyzer(
            self._sim_log_dir.name + "/trace_node_left.pcap", self._keylog_file()
        )

    def _server_trace(self):
        return TraceAnalyzer(
            self._sim_log_dir.name + "/trace_node_right.pcap", self._keylog_file()
        )

    # see https://www.stefanocappellini.it/generate-pseudorandom-bytes-with-python/ for benchmarks
    def _generate_random_file(self, size: int, filename_len=10) -> str:
        filename = random_string(filename_len)
        enc = AES.new(os.urandom(32), AES.MODE_OFB, b"a" * 16)
        f = open(self.www_dir() + filename, "wb")
        f.write(enc.encrypt(b" " * size))
        f.close()
        logging.debug("Generated random file: %s of size: %d", filename, size)
        return filename

    def _retry_sent(self) -> bool:
        return len(self._client_trace().get_retry()) > 0

    def _check_version_and_files(self) -> bool:
        versions = self._get_versions()
        if len(versions) != 1:
            logging.info("Expected exactly one version. Got %s", versions)
            return False
        if QUIC_VERSION not in versions:
            logging.info("Wrong version. Expected %s, got %s", QUIC_VERSION, versions)
            return False

        if len(self._files) == 0:
            raise Exception("No test files generated.")
        files = [
            n
            for n in os.listdir(self.download_dir())
            if os.path.isfile(os.path.join(self.download_dir(), n))
        ]
        too_many = [f for f in files if f not in self._files]
        if len(too_many) != 0:
            logging.info("Found unexpected downloaded files: %s", too_many)
        too_few = [f for f in self._files if f not in files]
        if len(too_few) != 0:
            logging.info("Missing files: %s", too_few)
        if len(too_many) != 0 or len(too_few) != 0:
            return False
        for f in self._files:
            fp = self.download_dir() + f
            if not os.path.isfile(fp):
                logging.info("File %s does not exist.", fp)
                return False
            try:
                size = os.path.getsize(self.www_dir() + f)
                downloaded_size = os.path.getsize(fp)
                if size != downloaded_size:
                    logging.info(
                        "File size of %s doesn't match. Original: %d bytes, downloaded: %d bytes.",
                        fp,
                        size,
                        downloaded_size,
                    )
                    return False
                if not filecmp.cmp(self.www_dir() + f, fp, shallow=False):
                    logging.info("File contents of %s do not match.", fp)
                    return False
            except Exception as exception:
                logging.info(
                    "Could not compare files %s and %s: %s",
                    self.www_dir() + f,
                    fp,
                    exception,
                )
                return False
        logging.debug("Check of downloaded files succeeded.")
        return True

    def _count_handshakes(self) -> int:
        """ Count the number of QUIC handshakes """
        tr = self._server_trace()
        # Determine the number of handshakes by looking at Initial packets.
        # This is easier, since the SCID of Initial packets doesn't changes.
        return len(set([p.scid for p in tr.get_initial(Direction.FROM_SERVER)]))

    def _get_versions(self) -> set:
        """ Get the QUIC versions """
        tr = self._server_trace()
        return set([p.version for p in tr.get_initial(Direction.FROM_SERVER)])

    def _payload_size(self, packets: List) -> int:
        """ Get the sum of the payload sizes of all packets """
        size = 0
        for p in packets:
            if hasattr(p, "long_packet_type"):
                if hasattr(p, "payload"):  # when keys are available
                    size += len(p.payload.split(":"))
                else:
                    size += len(p.remaining_payload.split(":"))
            else:
                if hasattr(p, "protected_payload"):
                    size += len(p.protected_payload.split(":"))
        return size

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
    def check(self) -> TestResult:
        pass


class Measurement(TestCase):
    @abc.abstractmethod
    def result(self) -> float:
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

    @staticmethod
    def desc():
        return "A version negotiation packet is elicited and acted on."

    def get_paths(self):
        return [""]

    def check(self) -> TestResult:
        tr = self._client_trace()
        initials = tr.get_initial(Direction.FROM_CLIENT)
        dcid = ""
        for p in initials:
            dcid = p.dcid
            break
        if dcid == "":
            logging.info("Didn't find an Initial / a DCID.")
            return TestResult.FAILED
        vnps = tr.get_vnp()
        for p in vnps:
            if p.scid == dcid:
                return TestResult.SUCCEEDED
        logging.info("Didn't find a Version Negotiation Packet with matching SCID.")
        return TestResult.FAILED


class TestCaseHandshake(TestCase):
    @staticmethod
    def name():
        return "handshake"

    @staticmethod
    def abbreviation():
        return "H"

    @staticmethod
    def desc():
        return "Handshake completes successfully."

    def get_paths(self):
        self._files = [self._generate_random_file(1 * KB)]
        return self._files

    def check(self) -> TestResult:
        if not self._check_version_and_files():
            return TestResult.FAILED
        if self._retry_sent():
            logging.info("Didn't expect a Retry to be sent.")
            return TestResult.FAILED
        num_handshakes = self._count_handshakes()
        if num_handshakes != 1:
            logging.info("Expected exactly 1 handshake. Got: %d", num_handshakes)
            return TestResult.FAILED
        return TestResult.SUCCEEDED


class TestCaseLongRTT(TestCaseHandshake):
    @staticmethod
    def abbreviation():
        return "LR"

    @staticmethod
    def name():
        return "longrtt"

    @staticmethod
    def testname(p: Perspective):
        return "handshake"

    @staticmethod
    def desc():
        return "Handshake completes when RTT is long."

    @staticmethod
    def scenario() -> str:
        """ Scenario for the ns3 simulator """
        return "simple-p2p --delay=750ms --bandwidth=10Mbps --queue=25"

    def check(self) -> TestResult:
        if not super(TestCaseLongRTT, self).check():
            return TestResult.FAILED
        num_ch = 0
        for p in self._client_trace().get_initial(Direction.FROM_CLIENT):
            if hasattr(p, "tls_handshake_type"):
                if p.tls_handshake_type == "1":
                    num_ch += 1
        if num_ch < 2:
            logging.info("Expected at least 2 ClientHellos. Got: %d", num_ch)
            return TestResult.FAILED
        return TestResult.SUCCEEDED


class TestCaseTransfer(TestCase):
    @staticmethod
    def name():
        return "transfer"

    @staticmethod
    def abbreviation():
        return "DC"

    @staticmethod
    def desc():
        return "Stream data is being sent and received correctly. Connection close completes with a zero error code."

    def get_paths(self):
        self._files = [
            self._generate_random_file(2 * MB),
            self._generate_random_file(3 * MB),
            self._generate_random_file(5 * MB),
        ]
        return self._files

    def check(self) -> TestResult:
        num_handshakes = self._count_handshakes()
        if num_handshakes != 1:
            logging.info("Expected exactly 1 handshake. Got: %d", num_handshakes)
            return TestResult.FAILED
        if not self._check_version_and_files():
            return TestResult.FAILED
        return TestResult.SUCCEEDED


class TestCaseChaCha20(TestCase):
    @staticmethod
    def name():
        return "chacha20"

    @staticmethod
    def testname(p: Perspective):
        if p is Perspective.CLIENT:
            return "chacha20"
        return "transfer"

    @staticmethod
    def abbreviation():
        return "C20"

    @staticmethod
    def desc():
        return "Handshake completes using ChaCha20."

    def get_paths(self):
        self._files = [self._generate_random_file(3 * MB)]
        return self._files

    def check(self) -> TestResult:
        num_handshakes = self._count_handshakes()
        if num_handshakes != 1:
            logging.info("Expected exactly 1 handshake. Got: %d", num_handshakes)
            return TestResult.FAILED
        ciphersuites = []
        for p in self._client_trace().get_initial(Direction.FROM_CLIENT):
            if hasattr(p, "tls_handshake_ciphersuite"):
                ciphersuites.append(p.tls_handshake_ciphersuite)
        if len(set(ciphersuites)) != 1 or ciphersuites[0] != "4867":
            logging.info(
                "Expected only ChaCha20 cipher suite to be offered. Got: %s",
                set(ciphersuites),
            )
            return TestResult.FAILED
        if not self._check_version_and_files():
            return TestResult.FAILED
        return TestResult.SUCCEEDED


class TestCaseMultiplexing(TestCase):
    @staticmethod
    def name():
        return "multiplexing"

    @staticmethod
    def testname(p: Perspective):
        return "transfer"

    @staticmethod
    def abbreviation():
        return "M"

    @staticmethod
    def desc():
        return "Thousands of files are transferred over a single connection, and server increased stream limits to accomodate client requests."

    def get_paths(self):
        for _ in range(1, 2000):
            self._files.append(self._generate_random_file(32))
        return self._files

    def check(self) -> TestResult:
        if not self._keylog_file():
            logging.info("Can't check test result. SSLKEYLOG required.")
            return TestResult.UNSUPPORTED
        num_handshakes = self._count_handshakes()
        if num_handshakes != 1:
            logging.info("Expected exactly 1 handshake. Got: %d", num_handshakes)
            return TestResult.FAILED
        if not self._check_version_and_files():
            return TestResult.FAILED
        # Check that the server set a bidirectional stream limit <= 1000
        checked_stream_limit = False
        for p in self._client_trace().get_handshake(Direction.FROM_SERVER):
            if hasattr(p, "tls.quic.parameter.initial_max_streams_bidi"):
                checked_stream_limit = True
                stream_limit = int(
                    getattr(p, "tls.quic.parameter.initial_max_streams_bidi")
                )
                logging.debug("Server set bidirectional stream limit: %d", stream_limit)
                if stream_limit > 1000:
                    logging.info("Server set a stream limit > 1000.")
                    return TestResult.FAILED
        if not checked_stream_limit:
            logging.info("Couldn't check stream limit.")
            return TestResult.FAILED
        return TestResult.SUCCEEDED


class TestCaseRetry(TestCase):
    @staticmethod
    def name():
        return "retry"

    @staticmethod
    def abbreviation():
        return "S"

    @staticmethod
    def desc():
        return "Server sends a Retry, and a subsequent connection using the Retry token completes successfully."

    def get_paths(self):
        self._files = [
            self._generate_random_file(10 * KB),
        ]
        return self._files

    def _check_trace(self) -> bool:
        # check that (at least) one Retry packet was actually sent
        tr = self._client_trace()
        tokens = []
        retries = tr.get_retry(Direction.FROM_SERVER)
        for p in retries:
            if not hasattr(p, "retry_token"):
                logging.info("Retry packet doesn't have a retry_token")
                logging.info(p)
                return False
            tokens += [p.retry_token.replace(":", "")]
        if len(tokens) == 0:
            logging.info("Didn't find any Retry packets.")
            return False

        # check that an Initial packet uses a token sent in the Retry packet(s)
        highest_pn_before_retry = -1
        for p in tr.get_initial(Direction.FROM_CLIENT):
            pn = int(p.packet_number)
            if p.token_length == "0":
                highest_pn_before_retry = max(highest_pn_before_retry, pn)
                continue
            if pn <= highest_pn_before_retry:
                logging.debug(
                    "Client reset the packet number. Check failed for PN %d", pn
                )
                return False
            token = p.token.replace(":", "")
            if token in tokens:
                logging.debug("Check of Retry succeeded. Token used: %s", token)
                return True
        logging.info("Didn't find any Initial packet using a Retry token.")
        return False

    def check(self) -> TestResult:
        num_handshakes = self._count_handshakes()
        if num_handshakes != 1:
            logging.info("Expected exactly 1 handshake. Got: %d", num_handshakes)
            return TestResult.FAILED
        if not self._check_version_and_files():
            return TestResult.FAILED
        if not self._check_trace():
            return TestResult.FAILED
        return TestResult.SUCCEEDED


class TestCaseResumption(TestCase):
    @staticmethod
    def name():
        return "resumption"

    @staticmethod
    def abbreviation():
        return "R"

    @staticmethod
    def desc():
        return "Connection is established using TLS Session Resumption."

    def get_paths(self):
        self._files = [
            self._generate_random_file(5 * KB),
            self._generate_random_file(10 * KB),
        ]
        return self._files

    def check(self) -> TestResult:
        num_handshakes = self._count_handshakes()
        if num_handshakes != 2:
            logging.info("Expected exactly 2 handshake. Got: %d", num_handshakes)
            return TestResult.FAILED

        handshake_packets = self._client_trace().get_handshake(Direction.FROM_SERVER)
        cids = [p.scid for p in handshake_packets]
        handshake_packets_first = []
        handshake_packets_second = []
        for p in handshake_packets:
            if p.scid == cids[0]:
                handshake_packets_first.append(p)
            elif p.scid == cids[len(cids) - 1]:
                handshake_packets_second.append(p)
            else:
                logging.info("This should never happen.")
                return TestResult.FAILED
        handshake_size_first = self._payload_size(handshake_packets_first)
        handshake_size_second = self._payload_size(handshake_packets_second)
        logging.debug(
            "Size of the server's Handshake flight (1st connection): %d",
            handshake_size_first,
        )
        logging.debug(
            "Size of the server's Handshake flight (2nd connection): %d",
            handshake_size_second,
        )
        # The second handshake doesn't contain a certificate, if session resumption is used.
        if handshake_size_first < handshake_size_second + 400:
            logging.info(
                "Expected the size of the server's Handshake flight to be significantly smaller during the second connection."
            )
            return TestResult.FAILED
        if not self._check_version_and_files():
            return TestResult.FAILED
        return TestResult.SUCCEEDED


class TestCaseZeroRTT(TestCase):
    NUM_FILES = 40
    FILESIZE = 32  # in bytes
    FILENAMELEN = 250

    @staticmethod
    def name():
        return "zerortt"

    @staticmethod
    def abbreviation():
        return "Z"

    @staticmethod
    def desc():
        return "0-RTT data is being sent and acted on."

    def get_paths(self):
        for _ in range(self.NUM_FILES):
            self._files.append(
                self._generate_random_file(self.FILESIZE, self.FILENAMELEN)
            )
        return self._files

    def check(self) -> TestResult:
        num_handshakes = self._count_handshakes()
        if num_handshakes != 2:
            logging.info("Expected exactly 2 handshakes. Got: %d", num_handshakes)
            return TestResult.FAILED
        if not self._check_version_and_files():
            return TestResult.FAILED
        tr = self._client_trace()
        zeroRTTSize = self._payload_size(tr.get_0rtt())
        oneRTTSize = self._payload_size(tr.get_1rtt(Direction.FROM_CLIENT))
        logging.debug("0-RTT size: %d", zeroRTTSize)
        logging.debug("1-RTT size: %d", oneRTTSize)
        if zeroRTTSize == 0:
            logging.info("Client didn't send any 0-RTT data.")
            return TestResult.FAILED
        if oneRTTSize > 0.5 * self.FILENAMELEN * self.NUM_FILES:
            logging.info("Client sent too much data in 1-RTT packets.")
            return TestResult.FAILED
        return TestResult.SUCCEEDED


class TestCaseHTTP3(TestCase):
    @staticmethod
    def name():
        return "http3"

    @staticmethod
    def abbreviation():
        return "3"

    @staticmethod
    def desc():
        return "An H3 transaction succeeded."

    def get_paths(self):
        self._files = [
            self._generate_random_file(5 * KB),
            self._generate_random_file(10 * KB),
            self._generate_random_file(500 * KB),
        ]
        return self._files

    def check(self) -> TestResult:
        num_handshakes = self._count_handshakes()
        if num_handshakes != 1:
            logging.info("Expected exactly 1 handshake. Got: %d", num_handshakes)
            return TestResult.FAILED
        if not self._check_version_and_files():
            return TestResult.FAILED
        return TestResult.SUCCEEDED


class TestCaseBlackhole(TestCase):
    @staticmethod
    def name():
        return "blackhole"

    @staticmethod
    def testname(p: Perspective):
        return "transfer"

    @staticmethod
    def abbreviation():
        return "B"

    @staticmethod
    def desc():
        return "Transfer succeeds despite underlying network blacking out for a few seconds."

    @staticmethod
    def scenario() -> str:
        """ Scenario for the ns3 simulator """
        return "blackhole --delay=15ms --bandwidth=10Mbps --queue=25 --on=5s --off=2s"

    def get_paths(self):
        self._files = [self._generate_random_file(10 * MB)]
        return self._files

    def check(self) -> TestResult:
        num_handshakes = self._count_handshakes()
        if num_handshakes != 1:
            logging.info("Expected exactly 1 handshake. Got: %d", num_handshakes)
            return TestResult.FAILED
        if not self._check_version_and_files():
            return TestResult.FAILED
        return TestResult.SUCCEEDED


class TestCaseKeyUpdate(TestCaseHandshake):
    @staticmethod
    def name():
        return "keyupdate"

    @staticmethod
    def testname(p: Perspective):
        if p is Perspective.CLIENT:
            return "keyupdate"
        return "transfer"

    @staticmethod
    def abbreviation():
        return "U"

    @staticmethod
    def desc():
        return "One of the two endpoints updates keys and the peer responds correctly."

    def get_paths(self):
        self._files = [self._generate_random_file(3 * MB)]
        return self._files

    def check(self) -> TestResult:
        if not self._keylog_file():
            logging.info("Can't check test result. SSLKEYLOG required.")
            return TestResult.UNSUPPORTED

        num_handshakes = self._count_handshakes()
        if num_handshakes != 1:
            logging.info("Expected exactly 1 handshake. Got: %d", num_handshakes)
            return TestResult.FAILED
        if not self._check_version_and_files():
            return TestResult.FAILED

        client = {0: 0, 1: 0}
        server = {0: 0, 1: 0}
        try:
            for p in self._client_trace().get_1rtt(Direction.FROM_CLIENT):
                client[int(p.key_phase)] += 1
            for p in self._server_trace().get_1rtt(Direction.FROM_SERVER):
                server[int(p.key_phase)] += 1
        except Exception:
            logging.info(
                "Failed to read key phase bits. Potentially incorrect SSLKEYLOG?"
            )
            return TestResult.FAILED

        succeeded = client[0] * client[1] * server[0] * server[1] > 0

        log_level = logging.INFO
        if succeeded:
            log_level = logging.DEBUG

        logging.log(
            log_level,
            "Client sent %d key phase 0 and %d key phase 1 packets.",
            client[0],
            client[1],
        )
        logging.log(
            log_level,
            "Server sent %d key phase 0 and %d key phase 1 packets.",
            server[0],
            server[1],
        )
        if not succeeded:
            logging.info(
                "Expected to see packets sent with two key phases from both client and server."
            )
            return TestResult.FAILED
        return TestResult.SUCCEEDED


class TestCaseHandshakeLoss(TestCase):
    _num_runs = 50

    @staticmethod
    def name():
        return "handshakeloss"

    @staticmethod
    def testname(p: Perspective):
        return "multiconnect"

    @staticmethod
    def abbreviation():
        return "L1"

    @staticmethod
    def desc():
        return "Handshake completes under extreme packet loss."

    @staticmethod
    def timeout() -> int:
        return 300

    @staticmethod
    def scenario() -> str:
        """ Scenario for the ns3 simulator """
        return "drop-rate --delay=15ms --bandwidth=10Mbps --queue=25 --rate_to_server=30 --rate_to_client=30"

    def get_paths(self):
        for _ in range(self._num_runs):
            self._files.append(self._generate_random_file(1 * KB))
        return self._files

    def check(self) -> TestResult:
        num_handshakes = self._count_handshakes()
        if num_handshakes != self._num_runs:
            logging.info(
                "Expected %d handshakes. Got: %d", self._num_runs, num_handshakes
            )
            return TestResult.FAILED
        if not self._check_version_and_files():
            return TestResult.FAILED
        return TestResult.SUCCEEDED


class TestCaseTransferLoss(TestCase):
    @staticmethod
    def name():
        return "transferloss"

    @staticmethod
    def testname(p: Perspective):
        return "transfer"

    @staticmethod
    def abbreviation():
        return "L2"

    @staticmethod
    def desc():
        return "Transfer completes under moderate packet loss."

    @staticmethod
    def scenario() -> str:
        """ Scenario for the ns3 simulator """
        return "drop-rate --delay=15ms --bandwidth=10Mbps --queue=25 --rate_to_server=2 --rate_to_client=2"

    def get_paths(self):
        # At a packet loss rate of 2% and a MTU of 1500 bytes, we can expect 27 dropped packets.
        self._files = [self._generate_random_file(2 * MB)]
        return self._files

    def check(self) -> TestResult:
        num_handshakes = self._count_handshakes()
        if num_handshakes != 1:
            logging.info("Expected exactly 1 handshake. Got: %d", num_handshakes)
            return TestResult.FAILED
        if not self._check_version_and_files():
            return TestResult.FAILED
        return TestResult.SUCCEEDED


class TestCaseHandshakeCorruption(TestCaseHandshakeLoss):
    @staticmethod
    def name():
        return "handshakecorruption"

    @staticmethod
    def abbreviation():
        return "C1"

    @staticmethod
    def desc():
        return "Handshake completes under extreme packet corruption."

    @staticmethod
    def scenario() -> str:
        """ Scenario for the ns3 simulator """
        return "corrupt-rate --delay=15ms --bandwidth=10Mbps --queue=25 --rate_to_server=30 --rate_to_client=30"


class TestCaseTransferCorruption(TestCaseTransferLoss):
    @staticmethod
    def name():
        return "transfercorruption"

    @staticmethod
    def abbreviation():
        return "C2"

    @staticmethod
    def desc():
        return "Transfer completes under moderate packet corruption."

    @staticmethod
    def scenario() -> str:
        """ Scenario for the ns3 simulator """
        return "corrupt-rate --delay=15ms --bandwidth=10Mbps --queue=25 --rate_to_server=2 --rate_to_client=2"


class TestCaseECN(TestCaseHandshake):
    @staticmethod
    def name():
        return "ecn"

    @staticmethod
    def abbreviation():
        return "E"

    def _count_ecn(self, tr):
        ecn = [0] * (max(ECN) + 1)
        for p in tr:
            e = int(getattr(p["ip"], "dsfield.ecn"))
            ecn[e] += 1
        for e in ECN:
            logging.debug("%s %d", e, ecn[e])
        return ecn

    def _check_ecn_any(self, e) -> bool:
        return e[ECN.ECT0] != 0 or e[ECN.ECT1] != 0

    def _check_ecn_marks(self, e) -> bool:
        return (
            e[ECN.NONE] == 0
            and e[ECN.CE] == 0
            and ((e[ECN.ECT0] == 0) != (e[ECN.ECT1] == 0))
        )

    def _check_ack_ecn(self, tr) -> bool:
        # NOTE: We only check whether the trace contains any ACK-ECN information, not whether it is valid
        for p in tr:
            if hasattr(p["quic"], "ack.ect0_count"):
                return True
        return False

    def check(self) -> TestResult:
        if not self._keylog_file():
            logging.info("Can't check test result. SSLKEYLOG required.")
            return TestResult.UNSUPPORTED

        result = super(TestCaseECN, self).check()
        if result != TestResult.SUCCEEDED:
            return result

        tr_client = self._client_trace()._get_packets(
            self._client_trace()._get_direction_filter(Direction.FROM_CLIENT) + " quic"
        )
        ecn = self._count_ecn(tr_client)
        ecn_client_any_marked = self._check_ecn_any(ecn)
        ecn_client_all_ok = self._check_ecn_marks(ecn)
        ack_ecn_client_ok = self._check_ack_ecn(tr_client)

        tr_server = self._server_trace()._get_packets(
            self._server_trace()._get_direction_filter(Direction.FROM_SERVER) + " quic"
        )
        ecn = self._count_ecn(tr_server)
        ecn_server_any_marked = self._check_ecn_any(ecn)
        ecn_server_all_ok = self._check_ecn_marks(ecn)
        ack_ecn_server_ok = self._check_ack_ecn(tr_server)

        if ecn_client_any_marked is False:
            logging.info("Client did not mark any packets ECT(0) or ECT(1)")
        else:
            if ack_ecn_server_ok is False:
                logging.info("Server did not send any ACK-ECN frames")
            elif ecn_client_all_ok is False:
                logging.info(
                    "Not all client packets were consistently marked with ECT(0) or ECT(1)"
                )

        if ecn_server_any_marked is False:
            logging.info("Server did not mark any packets ECT(0) or ECT(1)")
        else:
            if ack_ecn_client_ok is False:
                logging.info("Client did not send any ACK-ECN frames")
            elif ecn_server_all_ok is False:
                logging.info(
                    "Not all server packets were consistently marked with ECT(0) or ECT(1)"
                )

        if (
            ecn_client_all_ok
            and ecn_server_all_ok
            and ack_ecn_client_ok
            and ack_ecn_server_ok
        ):
            return TestResult.SUCCEEDED
        return TestResult.FAILED


class MeasurementGoodput(Measurement):
    FILESIZE = 10 * MB
    _result = 0.0

    @staticmethod
    def name():
        return "goodput"

    @staticmethod
    def unit() -> str:
        return "kbps"

    @staticmethod
    def testname(p: Perspective):
        return "transfer"

    @staticmethod
    def abbreviation():
        return "G"

    @staticmethod
    def desc():
        return "Measures connection goodput over a 10Mbps link."

    @staticmethod
    def repetitions() -> int:
        return 5

    def get_paths(self):
        self._files = [self._generate_random_file(self.FILESIZE)]
        return self._files

    def check(self) -> TestResult:
        num_handshakes = self._count_handshakes()
        if num_handshakes != 1:
            logging.info("Expected exactly 1 handshake. Got: %d", num_handshakes)
            return TestResult.FAILED
        if not self._check_version_and_files():
            return TestResult.FAILED

        packets = self._client_trace().get_1rtt(Direction.FROM_SERVER)
        first, last = 0, 0
        for p in packets:
            if first == 0:
                first = p.sniff_time
            last = p.sniff_time

        if last - first == 0:
            return TestResult.FAILED
        time = (last - first) / timedelta(milliseconds=1)
        goodput = (8 * self.FILESIZE) / time
        logging.debug(
            "Transfering %d MB took %d ms. Goodput: %d kbps",
            self.FILESIZE / MB,
            time,
            goodput,
        )
        self._result = goodput
        return TestResult.SUCCEEDED

    def result(self) -> float:
        return self._result


class MeasurementCrossTraffic(MeasurementGoodput):
    FILESIZE = 25 * MB

    @staticmethod
    def name():
        return "crosstraffic"

    @staticmethod
    def abbreviation():
        return "C"

    @staticmethod
    def desc():
        return "Measures goodput over a 10Mbps link when competing with a TCP (cubic) connection."

    @staticmethod
    def timeout() -> int:
        return 180

    @staticmethod
    def additional_envs() -> List[str]:
        return ["IPERF_CONGESTION=cubic"]

    @staticmethod
    def additional_containers() -> List[str]:
        return ["iperf_server", "iperf_client"]


TESTCASES = [
    TestCaseHandshake,
    TestCaseTransfer,
    TestCaseLongRTT,
    TestCaseChaCha20,
    TestCaseMultiplexing,
    TestCaseRetry,
    TestCaseResumption,
    TestCaseZeroRTT,
    TestCaseHTTP3,
    TestCaseBlackhole,
    TestCaseKeyUpdate,
    TestCaseECN,
    TestCaseHandshakeLoss,
    TestCaseTransferLoss,
    TestCaseHandshakeCorruption,
    TestCaseTransferCorruption,
]

MEASUREMENTS = [
    MeasurementGoodput,
    MeasurementCrossTraffic,
]
