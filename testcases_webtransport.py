import logging
import os
import random
from unique_random_slugs import generate_slug
from result import TestResult
from testcase import (
    TestCase,
    Perspective,
)

KB = 1 << 10
MB = 1 << 20


class TestCaseWebTransport(TestCase):
    _files_server = []
    _files_client = []


class TestCaseHandshake(TestCaseWebTransport):
    client_protocols = []
    server_protocols = []
    endpoint = generate_slug()

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
        os.makedirs(os.path.join(self.server_www_dir(), self.endpoint), exist_ok=True)
        return [self.urlprefix() + self.endpoint]

    def additional_envs(self):
        server_only = [generate_slug() for _ in range(5)]
        client_only = [generate_slug() for _ in range(5)]
        positions = sorted(random.sample(range(0, 5), 2))
        shared = [generate_slug(), generate_slug()]
        client_only[positions[0]], client_only[positions[1]] = shared[0], shared[1]
        server_only[positions[0]], server_only[positions[1]] = shared[1], shared[0]
        self.client_protocols = client_only
        self.server_protocols = server_only
        return [
            f'PROTOCOLS_CLIENT="{" ".join(self.client_protocols)}"',
            f'PROTOCOLS_SERVER="{" ".join(self.server_protocols)}"',
        ]

    def check(self) -> TestResult:
        num_handshakes = self._count_handshakes()
        if num_handshakes != 1:
            logging.info("Expected exactly 1 handshake. Got: %d", num_handshakes)
            return TestResult.FAILED

        # the client's first protocol that the server supports should be selected
        common_protocol = None
        for proto in self.client_protocols:
            if proto in self.server_protocols:
                common_protocol = proto
                break

        logging.info("Client protocols: %s", self.client_protocols)
        logging.info("Server protocols: %s", self.server_protocols)
        logging.info("Expected protocol: %s", common_protocol)

        # check negotiated protocol from client
        client_proto_path = self.client_download_dir() + "negotiated_protocol.txt"
        try:
            with open(client_proto_path, "r") as f:
                client_proto = f.read().strip()
        except Exception as e:
            logging.info("Failed to read client's negotiated_protocol.txt: %s", e)
            return TestResult.FAILED

        # check negotiated protocol from server
        server_proto_path = self.server_download_dir() + "negotiated_protocol.txt"
        try:
            with open(server_proto_path, "r") as f:
                server_proto = f.read().strip()
        except Exception as e:
            logging.info("Failed to read server's negotiated_protocol.txt: %s", e)
            return TestResult.FAILED

        if client_proto != common_protocol:
            logging.info(
                "Client's negotiated protocol '%s' does not match expected '%s'",
                client_proto,
                common_protocol,
            )
            return TestResult.FAILED
        if server_proto != common_protocol:
            logging.info(
                "Server's negotiated protocol '%s' does not match expected '%s'",
                server_proto,
                common_protocol,
            )
            return TestResult.FAILED

        return TestResult.SUCCEEDED


class TestCaseTransfer(TestCaseWebTransport):
    """Parameterized transfer test: stream_type in ('unidirectional', 'bidirectional', 'datagram'), direction in ('receive', 'send').
    Subclasses set _transfer_sizes to the list of file sizes to transfer.
    """

    _type: str  # "unidirectional" | "bidirectional" | "datagram"
    _direction: str  # "receive" | "send"
    _transfer_sizes = [100 * KB, 500 * KB, 250 * KB, 1 * MB, 2 * MB]

    @classmethod
    def name(cls):
        return f"transfer-{cls._type}-{cls._direction}"

    @classmethod
    def testname(cls, p: Perspective):
        full_name = cls.name()
        if cls._direction == "receive" and p is Perspective.CLIENT:
            return full_name
        if cls._direction == "send" and p is Perspective.SERVER:
            return full_name
        return "transfer"

    @classmethod
    def abbreviation(cls):
        stream_letter = (
            "U"
            if cls._type == "unidirectional"
            else "B" if cls._type == "bidirectional" else "D"
        )
        direction_letter = "R" if cls._direction == "receive" else "S"
        return stream_letter + direction_letter

    @classmethod
    def desc(cls):
        if cls._direction == "receive":
            who = "Server sends data to client"
        else:
            who = "Client sends data to server"
        if cls._type == "datagram":
            return f"{who} using datagrams"
        return f"{who} using {cls._type} streams"

    def __init__(self, sim_log_dir, client_keylog_file, server_keylog_file):
        super().__init__(sim_log_dir, client_keylog_file, server_keylog_file)
        endpoint = generate_slug()
        client_dir = os.path.join(self.client_www_dir(), endpoint)
        server_dir = os.path.join(self.server_www_dir(), endpoint)
        os.makedirs(client_dir, exist_ok=True)
        os.makedirs(server_dir, exist_ok=True)

        self._session_files = {endpoint: []}
        self._request_paths = []

        source_dir = server_dir if self._direction == "receive" else client_dir
        for size in self._transfer_sizes:
            filename = self._generate_random_file(size, directory=source_dir)
            self._session_files[endpoint].append(filename)
            self._request_paths.append(f"{endpoint}/{filename}")

        if self._direction == "receive":
            self._files_server = list(self._session_files[endpoint])
        else:
            self._files_client = list(self._session_files[endpoint])

    def additional_envs(self):
        protocol = generate_slug()
        return [
            "PROTOCOLS_CLIENT=" + protocol,
            "PROTOCOLS_SERVER=" + protocol,
        ]

    def get_paths(self):
        if self._direction == "receive":
            return [self.urlprefix() + p for p in self._request_paths]
        return [self.urlprefix() + next(iter(self._session_files))]

    def get_paths_server(self):
        if self._direction == "send":
            return self._request_paths
        return []

    def check(self) -> TestResult:
        num_handshakes = self._count_handshakes()
        if num_handshakes != 1:
            logging.info("Expected exactly 1 handshake. Got: %d", num_handshakes)
            return TestResult.FAILED

        if self._direction == "receive":
            source_root = self.server_www_dir()
            download_root = self.client_download_dir()
        else:
            source_root = self.client_www_dir()
            download_root = self.server_download_dir()

        for endpoint, files in self._session_files.items():
            source_dir = os.path.join(source_root, endpoint)
            download_dir = os.path.join(download_root, endpoint)
            if not os.path.isdir(download_dir):
                logging.info(
                    "Missing download directory for endpoint '%s': %s",
                    endpoint,
                    download_dir,
                )
                return TestResult.FAILED
            if not self._check_files(
                source_dir=source_dir, download_dir=download_dir, files=files
            ):
                return TestResult.FAILED

        return TestResult.SUCCEEDED


class TestCaseTransferUnidirectionalReceive(TestCaseTransfer):
    _type = "unidirectional"
    _direction = "receive"


class TestCaseTransferUnidirectionalSend(TestCaseTransfer):
    _type = "unidirectional"
    _direction = "send"


class TestCaseTransferBidirectionalReceive(TestCaseTransfer):
    _type = "bidirectional"
    _direction = "receive"


class TestCaseTransferBidirectionalSend(TestCaseTransfer):
    _type = "bidirectional"
    _direction = "send"


class TestCaseTransferDatagramReceive(TestCaseTransfer):
    _type = "datagram"
    _direction = "receive"
    _transfer_sizes = [600 + 2 * i for i in range(200)]


class TestCaseTransferDatagramSend(TestCaseTransfer):
    _type = "datagram"
    _direction = "send"
    _transfer_sizes = [600 + 2 * i for i in range(200)]


TESTCASES_WEBTRANSPORT = [
    TestCaseHandshake,
    TestCaseTransferUnidirectionalReceive,
    TestCaseTransferUnidirectionalSend,
    TestCaseTransferBidirectionalReceive,
    TestCaseTransferBidirectionalSend,
    TestCaseTransferDatagramReceive,
    TestCaseTransferDatagramSend,
]
