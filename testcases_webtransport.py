import logging
import random
from random_slugs import generate_slug
from result import TestResult
from testcase import TestCase

KB = 1 << 10
MB = 1 << 20


class TestCaseWebTransport(TestCase):
    def get_paths(self):
        return ["webtransport"]


class TestCaseHandshake(TestCaseWebTransport):
    client_protocols = []
    server_protocols = []

    @staticmethod
    def name():
        return "handshake"

    @staticmethod
    def abbreviation():
        return "H"

    @staticmethod
    def desc():
        return "Handshake completes successfully."

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
            "PROTOCOLS_CLIENT=" + ",".join(self.client_protocols),
            "PROTOCOLS_SERVER=" + ",".join(self.server_protocols),
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
                self.common_protocol,
            )
            return TestResult.FAILED
        if server_proto != common_protocol:
            logging.info(
                "Server's negotiated protocol '%s' does not match expected '%s'",
                server_proto,
                self.common_protocol,
            )
            return TestResult.FAILED

        return TestResult.SUCCEEDED


TESTCASES_WEBTRANSPORT = [
    TestCaseHandshake,
]

MEASUREMENTS = []
