import logging
from result import TestResult
from testcase import (
    TestCase,
)

KB = 1 << 10
MB = 1 << 20

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
        num_handshakes = self._count_handshakes()
        if num_handshakes != 1:
            logging.info("Expected exactly 1 handshake. Got: %d", num_handshakes)
            return TestResult.FAILED
        return TestResult.SUCCEEDED

TESTCASES_WEBTRANSPORT = [
    TestCaseHandshake,
]

MEASUREMENTS = []
