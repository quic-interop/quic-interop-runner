import abc
import filecmp
import logging
import os
import random
import string
import tempfile
from datetime import timedelta
from enum import Enum
from trace import Direction, TraceAnalyzer
from typing import List

from Crypto.Cipher import AES

KB = 1 << 10
MB = 1 << 20

QUIC_VERSION = "0xff00001d"  # draft-29


class Perspective(Enum):
    SERVER = "server"
    CLIENT = "client"


def random_string(length: int):
    """Generate a random string of fixed length """
    letters = string.ascii_lowercase
    return "".join(random.choice(letters) for i in range(length))


class TestCase(abc.ABC):
    _files = []
    _www_dir = None
    _download_dir = None
    _sim_log_dir = None

    def __init__(
        self, sim_log_dir: tempfile.TemporaryDirectory, client_keylog_file: str
    ):
        self._client_keylog_file = client_keylog_file
        self._files = []
        self._sim_log_dir = sim_log_dir

    @abc.abstractmethod
    def name(self):
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

    def _client_trace(self):
        return TraceAnalyzer(
            self._sim_log_dir.name + "/trace_node_left.pcap", self._client_keylog_file
        )

    def _server_trace(self):
        return TraceAnalyzer(
            self._sim_log_dir.name + "/trace_node_right.pcap", self._client_keylog_file
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
        num_files = len(
            [
                n
                for n in os.listdir(self.download_dir())
                if os.path.isfile(os.path.join(self.download_dir(), n))
            ]
        )
        if num_files != len(self._files):
            logging.info(
                "Downloaded the wrong number of files. Got %d, expected %d.",
                num_files,
                len(self._files),
            )
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
    def check(self) -> bool:
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

    def get_paths(self):
        return [""]

    def check(self):
        tr = self._client_trace()
        initials = tr.get_initial(Direction.FROM_CLIENT)
        dcid = ""
        for p in initials:
            dcid = p.dcid
            break
        if dcid == "":
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
        self._files = [self._generate_random_file(1 * KB)]
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
    def scenario() -> str:
        """ Scenario for the ns3 simulator """
        return "simple-p2p --delay=750ms --bandwidth=10Mbps --queue=25"

    def check(self):
        if not super(TestCaseLongRTT, self).check():
            return False
        num_ch = 0
        for p in self._client_trace().get_initial(Direction.FROM_CLIENT):
            if hasattr(p, "tls_handshake_type"):
                if p.tls_handshake_type == "1":
                    num_ch += 1
        if num_ch < 2:
            logging.info("Expected at least 2 ClientHellos. Got: %d", num_ch)
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
            self._generate_random_file(2 * MB),
            self._generate_random_file(3 * MB),
            self._generate_random_file(5 * MB),
        ]
        return self._files

    def check(self):
        num_handshakes = self._count_handshakes()
        if num_handshakes != 1:
            logging.info("Expected exactly 1 handshake. Got: %d", num_handshakes)
            return False
        return self._check_version_and_files()


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

    def get_paths(self):
        self._files = [self._generate_random_file(3 * MB)]
        return self._files

    def check(self):
        num_handshakes = self._count_handshakes()
        if num_handshakes != 1:
            logging.info("Expected exactly 1 handshake. Got: %d", num_handshakes)
            return False
        ciphersuites = []
        for p in self._client_trace().get_initial(Direction.FROM_CLIENT):
            if hasattr(p, "tls_handshake_ciphersuite"):
                ciphersuites.append(p.tls_handshake_ciphersuite)
        if len(set(ciphersuites)) != 1 or ciphersuites[0] != "4867":
            logging.info(
                "Expected only ChaCha20 cipher suite to be offered. Got: %s",
                set(ciphersuites),
            )
            return False
        return self._check_version_and_files()


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

    def get_paths(self):
        for _ in range(1, 2000):
            self._files.append(self._generate_random_file(32))
        return self._files

    def check(self):
        num_handshakes = self._count_handshakes()
        if num_handshakes != 1:
            logging.info("Expected exactly 1 handshake. Got: %d", num_handshakes)
            return False
        if not self._check_version_and_files():
            return False
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
                    return False
        if not checked_stream_limit:
            logging.debug(
                "WARNING: Couldn't check stream limit. No SSLKEYLOG file available?"
            )
        return True


class TestCaseRetry(TestCase):
    @staticmethod
    def name():
        return "retry"

    @staticmethod
    def abbreviation():
        return "S"

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
            self._generate_random_file(5 * KB),
            self._generate_random_file(10 * KB),
        ]
        return self._files

    def check(self):
        num_handshakes = self._count_handshakes()
        if num_handshakes != 2:
            logging.info("Expected exactly 2 handshake. Got: %d", num_handshakes)
            return False

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
                return False
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
            return False
        return self._check_version_and_files()


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

    def get_paths(self):
        for _ in range(self.NUM_FILES):
            self._files.append(
                self._generate_random_file(self.FILESIZE, self.FILENAMELEN)
            )
        return self._files

    def check(self) -> bool:
        num_handshakes = self._count_handshakes()
        if num_handshakes != 2:
            logging.info("Expected exactly 2 handshakes. Got: %d", num_handshakes)
            return False
        if not self._check_version_and_files():
            return False
        tr = self._client_trace()
        zeroRTTSize = self._payload_size(tr.get_0rtt())
        oneRTTSize = self._payload_size(tr.get_1rtt(Direction.FROM_CLIENT))
        logging.debug("0-RTT size: %d", zeroRTTSize)
        logging.debug("1-RTT size: %d", oneRTTSize)
        if zeroRTTSize == 0:
            logging.info("Client didn't send any 0-RTT data.")
            return False
        if oneRTTSize > 0.5 * self.FILENAMELEN * self.NUM_FILES:
            logging.info("Client sent too much data in 1-RTT packets.")
            return False
        return True


class TestCaseHTTP3(TestCase):
    @staticmethod
    def name():
        return "http3"

    @staticmethod
    def abbreviation():
        return "3"

    def get_paths(self):
        self._files = [
            self._generate_random_file(5 * KB),
            self._generate_random_file(10 * KB),
            self._generate_random_file(500 * KB),
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
    def testname(p: Perspective):
        return "transfer"

    @staticmethod
    def abbreviation():
        return "B"

    @staticmethod
    def scenario() -> str:
        """ Scenario for the ns3 simulator """
        return "blackhole --delay=15ms --bandwidth=10Mbps --queue=25 --on=5s --off=2s"

    def get_paths(self):
        self._files = [self._generate_random_file(10 * MB)]
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
    def testname(p: Perspective):
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
            self._files.append(self._generate_random_file(1 * KB))
        return self._files

    def check(self):
        num_handshakes = self._count_handshakes()
        if num_handshakes != self._num_runs:
            logging.info(
                "Expected %d handshakes. Got: %d", self._num_runs, num_handshakes
            )
            return False
        return self._check_version_and_files()


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
    def scenario() -> str:
        """ Scenario for the ns3 simulator """
        return "drop-rate --delay=15ms --bandwidth=10Mbps --queue=25 --rate_to_server=2 --rate_to_client=2"

    def get_paths(self):
        # At a packet loss rate of 2% and a MTU of 1500 bytes, we can expect 27 dropped packets.
        self._files = [self._generate_random_file(2 * MB)]
        return self._files

    def check(self):
        num_handshakes = self._count_handshakes()
        if num_handshakes != 1:
            logging.info("Expected exactly 1 handshake. Got: %d", num_handshakes)
            return False
        return self._check_version_and_files()


class TestCaseHandshakeCorruption(TestCaseHandshakeLoss):
    @staticmethod
    def name():
        return "handshakecorruption"

    @staticmethod
    def abbreviation():
        return "C1"

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
    def scenario() -> str:
        """ Scenario for the ns3 simulator """
        return "corrupt-rate --delay=15ms --bandwidth=10Mbps --queue=25 --rate_to_server=2 --rate_to_client=2"


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
    def repetitions() -> int:
        return 5

    def get_paths(self):
        self._files = [self._generate_random_file(self.FILESIZE)]
        return self._files

    def check(self) -> bool:
        num_handshakes = self._count_handshakes()
        if num_handshakes != 1:
            logging.info("Expected exactly 1 handshake. Got: %d", num_handshakes)
            return False
        if not self._check_version_and_files():
            return False

        packets = self._client_trace().get_1rtt(Direction.FROM_SERVER)
        first, last = 0, 0
        for p in packets:
            if first == 0:
                first = p.sniff_time
            last = p.sniff_time

        if last - first == 0:
            return False
        time = (last - first) / timedelta(milliseconds=1)
        goodput = (8 * self.FILESIZE) / time
        logging.debug(
            "Transfering %d MB took %d ms. Goodput: %d kbps",
            self.FILESIZE / MB,
            time,
            goodput,
        )
        self._result = goodput
        return True

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
    TestCaseHandshakeLoss,
    TestCaseTransferLoss,
    TestCaseHandshakeCorruption,
    TestCaseTransferCorruption,
]

MEASUREMENTS = [
    MeasurementGoodput,
    MeasurementCrossTraffic,
]
