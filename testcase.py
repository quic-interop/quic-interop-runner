import abc
import tempfile
import logging
import subprocess
import filecmp
import shutil
import sys
from unique_random_slugs import generate_slug
import os
import re
from enum import Enum
from Crypto.Cipher import AES
from trace import Direction, TraceAnalyzer
from typing import List

from result import TestResult

QUIC_VERSION = hex(0x1)


class Perspective(Enum):
    SERVER = "server"
    CLIENT = "client"


class MeasurementResult:
    result = TestResult
    details = str


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
    _client_keylog_file = None
    _server_keylog_file = None
    _sim_log_dir = None
    _cert_dir = None
    _cached_server_trace = None
    _cached_client_trace = None
    _client_www_dir = None
    _client_download_dir = None
    _server_www_dir = None
    _server_download_dir = None

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

    def client_www_dir(self):
        if not self._client_www_dir:
            self._client_www_dir = tempfile.TemporaryDirectory(
                dir="/tmp", prefix="client_www_"
            )
        return self._client_www_dir.name + "/"

    def client_download_dir(self):
        if not self._client_download_dir:
            self._client_download_dir = tempfile.TemporaryDirectory(
                dir="/tmp", prefix="client_download_"
            )
        return self._client_download_dir.name + "/"

    def server_www_dir(self):
        if not self._server_www_dir:
            self._server_www_dir = tempfile.TemporaryDirectory(
                dir="/tmp", prefix="server_www_"
            )
        return self._server_www_dir.name + "/"

    def server_download_dir(self):
        if not self._server_download_dir:
            self._server_download_dir = tempfile.TemporaryDirectory(
                dir="/tmp", prefix="server_download_"
            )
        return self._server_download_dir.name + "/"

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

    def _inject_keylog_if_possible(self, trace: str):
        """
        Inject the keylog file into the pcap file if it is available and valid.
        """
        keylog = self._keylog_file()
        if keylog is None:
            return

        with tempfile.NamedTemporaryFile() as tmp:
            r = subprocess.run(
                f"editcap --inject-secrets tls,{keylog} {trace} {tmp.name}",
                shell=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
            )
            logging.debug("%s", r.stdout.decode("utf-8"))
            if r.returncode != 0:
                return
            shutil.copy(tmp.name, trace)

    def _client_trace(self):
        if self._cached_client_trace is None:
            trace = self._sim_log_dir.name + "/trace_node_left.pcap"
            self._inject_keylog_if_possible(trace)
            self._cached_client_trace = TraceAnalyzer(trace, self._keylog_file())
        return self._cached_client_trace

    def _server_trace(self):
        if self._cached_server_trace is None:
            trace = self._sim_log_dir.name + "/trace_node_right.pcap"
            self._inject_keylog_if_possible(trace)
            self._cached_server_trace = TraceAnalyzer(trace, self._keylog_file())
        return self._cached_server_trace

    def _generate_random_file(self, size: int, filename: str = None) -> str:
        if filename is None:
            filename = generate_slug()
        # see https://www.stefanocappellini.it/generate-pseudorandom-bytes-with-python/ for benchmarks
        enc = AES.new(os.urandom(32), AES.MODE_OFB, b"a" * 16)
        f = open(self.server_www_dir() + filename, "wb")
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
            for n in os.listdir(self.client_download_dir())
            if os.path.isfile(os.path.join(self.client_download_dir(), n))
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
            fp = self.client_download_dir() + f
            if not os.path.isfile(fp):
                logging.info("File %s does not exist.", fp)
                return False
            try:
                size = os.path.getsize(self.server_www_dir() + f)
                downloaded_size = os.path.getsize(fp)
                if size != downloaded_size:
                    logging.info(
                        "File size of %s doesn't match. Original: %d bytes, downloaded: %d bytes.",
                        fp,
                        size,
                        downloaded_size,
                    )
                    return False
                if not filecmp.cmp(self.server_www_dir() + f, fp, shallow=False):
                    logging.info("File contents of %s do not match.", fp)
                    return False
            except Exception as exception:
                logging.info(
                    "Could not compare files %s and %s: %s",
                    self.server_www_dir() + f,
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
        if self._client_www_dir:
            self._client_www_dir.cleanup()
            self._client_www_dir = None
        if self._client_download_dir:
            self._client_download_dir.cleanup()
            self._client_download_dir = None
        if self._server_www_dir:
            self._server_www_dir.cleanup()
            self._server_www_dir = None
        if self._server_download_dir:
            self._server_download_dir.cleanup()
            self._server_download_dir = None

    @abc.abstractmethod
    def get_paths(self):
        pass

    @abc.abstractmethod
    def check(self) -> TestResult:
        self._client_trace()
        self._server_trace()
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
