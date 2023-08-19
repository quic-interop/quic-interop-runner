import abc
import filecmp
import logging
import os
import random
import re
import string
import subprocess
import sys
import tempfile
from datetime import timedelta
from enum import Enum, IntEnum
from trace import (
    QUIC_V2,
    Direction,
    PacketType,
    TraceAnalyzer,
    get_direction,
    get_packet_type,
)
from typing import List

from Crypto.Cipher import AES

from result import TestResult

KB = 1 << 10
MB = 1 << 20

QUIC_DRAFT = 34  # draft-34
QUIC_VERSION = hex(0x1)


class Perspective(Enum):
    SERVER = "server"
    CLIENT = "client"


class ECN(IntEnum):
    NONE = 0
    ECT1 = 1
    ECT0 = 2
    CE = 3


def random_string(length: int):
    """Generate a random string of fixed length"""
    letters = string.ascii_lowercase
    return "".join(random.choice(letters) for i in range(length))


def generate_cert_chain(directory: str, length: int = 1):
    cmd = "./certs.sh " + directory + " " + str(length)
    r = subprocess.run(
        cmd, shell=True, stdout=subprocess.PIPE, stderr=subprocess.STDOUT
    )
    logging.debug("%s", r.stdout.decode("utf-8"))
    if r.returncode != 0:
        logging.info("Unable to create certificates")
        sys.exit(1)


class TestCase(abc.ABC):
    _files = []
    _www_dir = None
    _client_keylog_file = None
    _server_keylog_file = None
    _download_dir = None
    _sim_log_dir = None
    _cert_dir = None
    _cached_server_trace = None
    _cached_client_trace = None

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
        """The name of testcase presented to the endpoint Docker images"""
        return self.name()

    @staticmethod
    def scenario() -> str:
        """Scenario for the ns3 simulator"""
        return "simple-p2p --delay=15ms --bandwidth=10Mbps --queue=25"

    @staticmethod
    def timeout() -> int:
        """timeout in s"""
        return 60

    @staticmethod
    def urlprefix() -> str:
        """URL prefix"""
        return "https://server4:443/"

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

    def certs_dir(self):
        if not self._cert_dir:
            self._cert_dir = tempfile.TemporaryDirectory(dir="/tmp", prefix="certs_")
            generate_cert_chain(self._cert_dir.name)
        return self._cert_dir.name + "/"

    def _is_valid_keylog(self, filename) -> bool:
        if not os.path.isfile(filename) or os.path.getsize(filename) == 0:
            return False
        with open(filename, "r") as file:
            if not re.search(
                r"^SERVER_HANDSHAKE_TRAFFIC_SECRET", file.read(), re.MULTILINE
            ):
                logging.info("Key log file %s is using incorrect format.", filename)
                return False
        return True

    def _keylog_file(self) -> str:
        if self._is_valid_keylog(self._client_keylog_file):
            logging.debug("Using the client's key log file.")
            return self._client_keylog_file
        elif self._is_valid_keylog(self._server_keylog_file):
            logging.debug("Using the server's key log file.")
            return self._server_keylog_file
        logging.debug("No key log file found.")

    def _client_trace(self):
        if self._cached_client_trace is None:
            self._cached_client_trace = TraceAnalyzer(
                self._sim_log_dir.name + "/trace_node_left.pcap", self._keylog_file()
            )
        return self._cached_client_trace

    def _server_trace(self):
        if self._cached_server_trace is None:
            self._cached_server_trace = TraceAnalyzer(
                self._sim_log_dir.name + "/trace_node_right.pcap", self._keylog_file()
            )
        return self._cached_server_trace

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
        versions = [hex(int(v, 0)) for v in self._get_versions()]
        if len(versions) != 1:
            logging.info("Expected exactly one version. Got %s", versions)
            return False
        if QUIC_VERSION not in versions:
            logging.info("Wrong version. Expected %s, got %s", QUIC_VERSION, versions)
            return False
        return self._check_files()

    def _check_files(self) -> bool:
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
        """Count the number of QUIC handshakes"""
        tr = self._server_trace()
        # Determine the number of handshakes by looking at Initial packets.
        # This is easier, since the SCID of Initial packets doesn't changes.
        return len(set([p.scid for p in tr.get_initial(Direction.FROM_SERVER)]))

    def _get_versions(self) -> set:
        """Get the QUIC versions"""
        tr = self._server_trace()
        return set([p.version for p in tr.get_initial(Direction.FROM_SERVER)])

    def _payload_size(self, packets: List) -> int:
        """Get the sum of the payload sizes of all packets"""
        size = 0
        for p in packets:
            if hasattr(p, "long_packet_type") or hasattr(p, "long_packet_type_v2"):
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
        """Scenario for the ns3 simulator"""
        return "simple-p2p --delay=750ms --bandwidth=10Mbps --queue=25"

    def check(self) -> TestResult:
        num_handshakes = self._count_handshakes()
        if num_handshakes != 1:
            logging.info("Expected exactly 1 handshake. Got: %d", num_handshakes)
            return TestResult.FAILED
        if not self._check_version_and_files():
            return TestResult.FAILED
        num_ch = 0
        for p in self._client_trace().get_initial(Direction.FROM_CLIENT):
            if hasattr(p, "tls_handshake_type"):
                if p.tls_handshake_type == "1":
                    num_ch += 1
            # Retransmitted ClientHello does not have
            # tls_handshake_type attribute.  See
            # https://gitlab.com/wireshark/wireshark/-/issues/18696
            # for details.
            elif hasattr(p, "retransmission") or hasattr(p, "overlap"):
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
        return "chacha20"

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
        if len(set(ciphersuites)) != 1 or (
            ciphersuites[0] != "4867" and ciphersuites[0] != "0x1303"
        ):
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
        if not self._keylog_file():
            logging.info("Can't check test result. SSLKEYLOG required.")
            return TestResult.UNSUPPORTED
        num_handshakes = self._count_handshakes()
        if num_handshakes != 2:
            logging.info("Expected exactly 2 handshake. Got: %d", num_handshakes)
            return TestResult.FAILED

        handshake_packets = self._client_trace().get_handshake(Direction.FROM_SERVER)
        cids = [p.scid for p in handshake_packets]
        first_handshake_has_cert = False
        for p in handshake_packets:
            if p.scid == cids[0]:
                if hasattr(p, "tls_handshake_certificates_length"):
                    first_handshake_has_cert = True
            elif p.scid == cids[len(cids) - 1]:  # second handshake
                if hasattr(p, "tls_handshake_certificates_length"):
                    logging.info(
                        "Server sent a Certificate message in the second handshake."
                    )
                    return TestResult.FAILED
            else:
                logging.info(
                    "Found handshake packet that neither belongs to the first nor the second handshake."
                )
                return TestResult.FAILED
        if not first_handshake_has_cert:
            logging.info(
                "Didn't find a Certificate message in the first handshake. That's weird."
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


class TestCaseAmplificationLimit(TestCase):
    @staticmethod
    def name():
        return "amplificationlimit"

    @staticmethod
    def testname(p: Perspective):
        return "transfer"

    @staticmethod
    def abbreviation():
        return "A"

    @staticmethod
    def desc():
        return "The server obeys the 3x amplification limit."

    def certs_dir(self):
        if not self._cert_dir:
            self._cert_dir = tempfile.TemporaryDirectory(dir="/tmp", prefix="certs_")
            generate_cert_chain(self._cert_dir.name, 9)
        return self._cert_dir.name + "/"

    @staticmethod
    def scenario() -> str:
        """Scenario for the ns3 simulator"""
        # Let the ClientHello pass, but drop a bunch of retransmissions afterwards.
        return "droplist --delay=15ms --bandwidth=10Mbps --queue=25 --drops_to_server=2,3,4,5,6,7"

    def get_paths(self):
        self._files = [self._generate_random_file(5 * KB)]
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
        # Check the highest offset of CRYPTO frames sent by the server.
        # This way we can make sure that it actually used the provided cert chain.
        max_handshake_offset = 0
        for p in self._server_trace().get_handshake(Direction.FROM_SERVER):
            if hasattr(p, "crypto_offset"):
                max_handshake_offset = max(
                    max_handshake_offset, int(p.crypto_offset) + int(p.crypto_length)
                )
        if max_handshake_offset < 7500:
            logging.info(
                "Server sent too little Handshake CRYPTO data (%d bytes). Not using the provided cert chain?",
                max_handshake_offset,
            )
            return TestResult.FAILED
        logging.debug(
            "Server sent %d bytes in Handshake CRYPTO frames.", max_handshake_offset
        )

        # Check that the server didn't send more than 3-4x what the client sent.
        allowed = 0
        allowed_with_tolerance = 0
        client_sent, server_sent = 0, 0  # only for debug messages
        res = TestResult.FAILED
        log_output = []
        for p in self._server_trace().get_raw_packets():
            direction = get_direction(p)
            packet_type = get_packet_type(p)
            if packet_type == PacketType.VERSIONNEGOTIATION:
                logging.info("Didn't expect a Version Negotiation packet.")
                return TestResult.FAILED
            packet_size = int(p.udp.length) - 8  # subtract the UDP header length
            if packet_type == PacketType.INVALID:
                logging.debug("Couldn't determine packet type.")
                return TestResult.FAILED
            if direction == Direction.FROM_CLIENT:
                if packet_type is PacketType.HANDSHAKE:
                    res = TestResult.SUCCEEDED
                    break
                if packet_type is PacketType.INITIAL:
                    client_sent += packet_size
                    allowed += 3 * packet_size
                    allowed_with_tolerance += 4 * packet_size
                    log_output.append(
                        "Received a {} byte Initial packet from the client. Amplification limit: {}".format(
                            packet_size, 3 * client_sent
                        )
                    )
            elif direction == Direction.FROM_SERVER:
                server_sent += packet_size
                log_output.append(
                    "Received a {} byte Handshake packet from the server. Total: {}".format(
                        packet_size, server_sent
                    )
                )
                if packet_size >= allowed_with_tolerance:
                    log_output.append("Server violated the amplification limit.")
                    break
                if packet_size > allowed:
                    log_output.append(
                        "Server violated the amplification limit, but stayed within 3-4x amplification. Letting it slide."
                    )
                allowed_with_tolerance -= packet_size
                allowed -= packet_size
            else:
                logging.debug("Couldn't determine sender of packet.")
                return TestResult.FAILED

        log_level = logging.DEBUG
        if res == TestResult.FAILED:
            log_level = logging.INFO
        for msg in log_output:
            logging.log(log_level, msg)
        return res


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
        """Scenario for the ns3 simulator"""
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

        succeeded = client[1] * server[1] > 0

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
                "Expected to see packets sent with key phase 1 from both client and server."
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
        """Scenario for the ns3 simulator"""
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
        """Scenario for the ns3 simulator"""
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
        """Scenario for the ns3 simulator"""
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
        """Scenario for the ns3 simulator"""
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


class TestCasePortRebinding(TestCaseTransfer):
    @staticmethod
    def name():
        return "rebind-port"

    @staticmethod
    def abbreviation():
        return "BP"

    @staticmethod
    def testname(p: Perspective):
        return "transfer"

    @staticmethod
    def desc():
        return "Transfer completes under frequent port rebindings on the client side."

    def get_paths(self):
        self._files = [
            self._generate_random_file(10 * MB),
        ]
        return self._files

    @staticmethod
    def scenario() -> str:
        """Scenario for the ns3 simulator"""
        return "rebind --delay=15ms --bandwidth=10Mbps --queue=25 --first-rebind=1s --rebind-freq=5s"

    def check(self) -> TestResult:
        if not self._keylog_file():
            logging.info("Can't check test result. SSLKEYLOG required.")
            return TestResult.UNSUPPORTED

        result = super(TestCasePortRebinding, self).check()
        if result != TestResult.SUCCEEDED:
            return result

        tr_server = self._server_trace()._get_packets(
            self._server_trace()._get_direction_filter(Direction.FROM_SERVER) + " quic"
        )

        ports = list(set(getattr(p["udp"], "dstport") for p in tr_server))

        logging.info("Server saw these client ports: %s", ports)
        if len(ports) <= 1:
            logging.info("Server saw only a single client port in use; test broken?")
            return TestResult.FAILED

        last = None
        num_migrations = 0
        for p in tr_server:
            cur = (
                getattr(p["ipv6"], "dst")
                if "IPV6" in str(p.layers)
                else getattr(p["ip"], "dst"),
                int(getattr(p["udp"], "dstport")),
            )
            if last is None:
                last = cur
                continue

            if last != cur:
                last = cur
                num_migrations += 1
                # packet to different IP/port, should have a PATH_CHALLENGE frame
                if hasattr(p["quic"], "path_challenge.data") is False:
                    logging.info(
                        "First server packet to new client destination %s did not contain a PATH_CHALLENGE frame",
                        cur,
                    )
                    logging.info(p["quic"])
                    return TestResult.FAILED

        tr_client = self._client_trace()._get_packets(
            self._client_trace()._get_direction_filter(Direction.FROM_CLIENT) + " quic"
        )

        challenges = list(
            set(
                getattr(p["quic"], "path_challenge.data")
                for p in tr_server
                if hasattr(p["quic"], "path_challenge.data")
            )
        )
        if len(challenges) < num_migrations:
            logging.info(
                "Saw %d migrations, but only %d unique PATH_CHALLENGE frames",
                len(challenges),
                num_migrations,
            )
            return TestResult.FAILED

        responses = list(
            set(
                getattr(p["quic"], "path_response.data")
                for p in tr_client
                if hasattr(p["quic"], "path_response.data")
            )
        )

        unresponded = [c for c in challenges if c not in responses]
        if unresponded != []:
            logging.info("PATH_CHALLENGE without a PATH_RESPONSE: %s", unresponded)
            return TestResult.FAILED

        return TestResult.SUCCEEDED


class TestCaseAddressRebinding(TestCasePortRebinding):
    @staticmethod
    def name():
        return "rebind-addr"

    @staticmethod
    def abbreviation():
        return "BA"

    @staticmethod
    def desc():
        return "Transfer completes under frequent IP address and port rebindings on the client side."

    @staticmethod
    def scenario() -> str:
        """Scenario for the ns3 simulator"""
        return (
            super(TestCaseAddressRebinding, TestCaseAddressRebinding).scenario()
            + " --rebind-addr"
        )

    def check(self) -> TestResult:
        if not self._keylog_file():
            logging.info("Can't check test result. SSLKEYLOG required.")
            return TestResult.UNSUPPORTED

        tr_server = self._server_trace()._get_packets(
            self._server_trace()._get_direction_filter(Direction.FROM_SERVER) + " quic"
        )

        ips = set()
        for p in tr_server:
            ip_vers = "ip"
            if "IPV6" in str(p.layers):
                ip_vers = "ipv6"
            ips.add(getattr(p[ip_vers], "dst"))

        logging.info("Server saw these client addresses: %s", ips)
        if len(ips) <= 1:
            logging.info(
                "Server saw only a single client IP address in use; test broken?"
            )
            return TestResult.FAILED

        result = super(TestCaseAddressRebinding, self).check()
        if result != TestResult.SUCCEEDED:
            return result

        return TestResult.SUCCEEDED


class TestCaseIPv6(TestCaseTransfer):
    @staticmethod
    def name():
        return "ipv6"

    @staticmethod
    def abbreviation():
        return "6"

    @staticmethod
    def testname(p: Perspective):
        return "transfer"

    @staticmethod
    def urlprefix() -> str:
        return "https://server6:443/"

    @staticmethod
    def desc():
        return "A transfer across an IPv6-only network succeeded."

    def get_paths(self):
        self._files = [
            self._generate_random_file(5 * KB),
            self._generate_random_file(10 * KB),
        ]
        return self._files

    def check(self) -> TestResult:
        result = super(TestCaseIPv6, self).check()
        if result != TestResult.SUCCEEDED:
            return result

        tr_server = self._server_trace()._get_packets(
            self._server_trace()._get_direction_filter(Direction.FROM_SERVER)
            + " quic && ip"
        )

        if tr_server:
            logging.info("Packet trace contains %s IPv4 packets.", len(tr_server))
            return TestResult.FAILED
        return TestResult.SUCCEEDED


class TestCaseConnectionMigration(TestCaseAddressRebinding):
    @staticmethod
    def name():
        return "connectionmigration"

    @staticmethod
    def abbreviation():
        return "CM"

    @staticmethod
    def testname(p: Perspective):
        if p is Perspective.CLIENT:
            return "connectionmigration"
        return "transfer"

    @staticmethod
    def desc():
        return "A transfer succeeded during which the client performed an active migration."

    @staticmethod
    def scenario() -> str:
        return super(TestCaseTransfer, TestCaseTransfer).scenario()

    def get_paths(self):
        self._files = [
            self._generate_random_file(2 * MB),
        ]
        return self._files

    def check(self) -> TestResult:
        # The parent check() method ensures that the client changed addresses
        # and that PATH_CHALLENGE/RESPONSE frames were sent and received
        result = super(TestCaseConnectionMigration, self).check()
        if result != TestResult.SUCCEEDED:
            return result

        tr_client = self._client_trace()._get_packets(
            self._client_trace()._get_direction_filter(Direction.FROM_CLIENT) + " quic"
        )

        last = None
        dcid = None
        for p in tr_client:
            cur = (
                getattr(p["ipv6"], "src")
                if "IPV6" in str(p.layers)
                else getattr(p["ip"], "src"),
                int(getattr(p["udp"], "srcport")),
            )
            if last is None:
                last = cur
                dcid = getattr(p["quic"], "dcid")
                continue

            if last != cur:
                last = cur
                # packet to different IP/port, should have a new DCID
                if dcid == getattr(p["quic"], "dcid"):
                    logging.info(
                        "First client packet during active migration to %s used previous DCID %s",
                        cur,
                        dcid,
                    )
                    logging.info(p["quic"])
                    return TestResult.FAILED
                dcid = getattr(p["quic"], "dcid")
                logging.info(
                    "DCID changed to %s during active migration to %s", dcid, cur
                )

        return TestResult.SUCCEEDED


class TestCaseV2(TestCase):
    @staticmethod
    def name():
        return "v2"

    @staticmethod
    def abbreviation():
        return "V2"

    @staticmethod
    def desc():
        return "Server should select QUIC v2 in compatible version negotiation."

    def get_paths(self):
        self._files = [self._generate_random_file(1 * KB)]
        return self._files

    def check(self) -> TestResult:
        # Client should initially send QUIC v1 packet.  It may send
        # QUIC v2 packet.
        versions = self._get_packet_versions(
            self._client_trace().get_initial(Direction.FROM_CLIENT)
        )
        if QUIC_VERSION not in versions:
            logging.info(
                "Wrong version in client Initial. Expected %s, got %s",
                QUIC_VERSION,
                versions,
            )
            return TestResult.FAILED

        # Server Initial packets should have QUIC v2.  It may send
        # QUIC v1 packet before sending CRYPTO frame.
        versions = self._get_packet_versions(
            self._server_trace().get_initial(Direction.FROM_SERVER)
        )
        if QUIC_V2 not in versions:
            logging.info(
                "Wrong version in server Initial. Expected %s, got %s",
                QUIC_V2,
                versions,
            )
            return TestResult.FAILED

        # Client should use QUIC v2 for all Handshake packets.
        versions = self._get_packet_versions(
            self._client_trace().get_handshake(Direction.FROM_CLIENT)
        )
        if len(versions) != 1:
            logging.info(
                "Expected exactly one version in client Handshake. Got %s", versions
            )
            return TestResult.FAILED
        if QUIC_V2 not in versions:
            logging.info(
                "Wrong version in client Handshake. Expected %s, got %s",
                QUIC_V2,
                versions,
            )
            return TestResult.FAILED

        # Server should use QUIC v2 for all Handshake packets.
        versions = self._get_packet_versions(
            self._server_trace().get_handshake(Direction.FROM_SERVER)
        )
        if len(versions) != 1:
            logging.info(
                "Expected exactly one version in server Handshake. Got %s", versions
            )
            return TestResult.FAILED
        if QUIC_V2 not in versions:
            logging.info(
                "Wrong version in server Handshake. Expected %s, got %s",
                QUIC_V2,
                versions,
            )
            return TestResult.FAILED

        if not self._check_files():
            return TestResult.FAILED

        return TestResult.SUCCEEDED

    def _get_packet_versions(self, packets: List) -> set:
        """Get a set of QUIC versions from packets."""
        return set([hex(int(p.version, 0)) for p in packets])


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

        packets, first, last = self._client_trace().get_1rtt_sniff_times(
            Direction.FROM_SERVER
        )

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
    TestCaseAmplificationLimit,
    TestCaseHandshakeLoss,
    TestCaseTransferLoss,
    TestCaseHandshakeCorruption,
    TestCaseTransferCorruption,
    TestCaseIPv6,
    TestCaseV2,
    # The next three tests are disabled due to Wireshark not being able
    # to decrypt packets sent on the new path.
    # TestCasePortRebinding,
    # TestCaseAddressRebinding,
    # TestCaseConnectionMigration,
]

MEASUREMENTS = [
    MeasurementGoodput,
    MeasurementCrossTraffic,
]
