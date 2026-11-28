import os
import shutil
import tempfile
import unittest

import testcases_webtransport
from result import TestResult

DATA_DIR = os.path.join(os.path.dirname(__file__), "data")


class CheckTest(unittest.TestCase):
    """
    Run the check of a test case on the captures of a past interop run.

    The captures are taken from tests/data/<protocol>/<test case>/<server>_<client>.
    The negotiated protocols and the transferred files are written as the
    endpoints would, so that the check only depends on the captures.
    """

    def run_check(self, test_class, fixture):
        # The check injects the TLS secrets into the captures, work on a copy. On
        # some CI runners tshark cannot read files outside the temporary directory.
        sim_log_dir = tempfile.TemporaryDirectory()
        self.addCleanup(sim_log_dir.cleanup)
        shutil.copytree(
            os.path.join(DATA_DIR, fixture), sim_log_dir.name, dirs_exist_ok=True
        )

        test = test_class(
            sim_log_dir=sim_log_dir,
            client_keylog_file=os.path.join(sim_log_dir.name, "client_keys.log"),
            server_keylog_file=os.path.join(sim_log_dir.name, "server_keys.log"),
        )
        self.addCleanup(test.cleanup)
        test.get_paths()
        test.additional_envs()

        if isinstance(test, testcases_webtransport.TestCaseHandshake):
            protocol = next(
                p for p in test.client_protocols if p in test.server_protocols
            )
            for download_dir in [
                test.client_download_dir(),
                test.server_download_dir(),
            ]:
                with open(
                    os.path.join(download_dir, "negotiated_protocol.txt"), "w"
                ) as f:
                    f.write(protocol)
        else:
            if test._direction == "receive":
                source_root, download_root = (
                    test.server_www_dir(),
                    test.client_download_dir(),
                )
            else:
                source_root, download_root = (
                    test.client_www_dir(),
                    test.server_download_dir(),
                )
            for endpoint in test._session_files:
                shutil.copytree(
                    os.path.join(source_root, endpoint),
                    os.path.join(download_root, endpoint),
                )

        with self.assertLogs(level="DEBUG") as logs:
            result = test.check()
        return result, "\n".join(record.getMessage() for record in logs.records)

    def assertCheck(self, test_class, fixture, expected_result, expected_messages):
        result, messages = self.run_check(test_class, fixture)
        for expected_message in expected_messages:
            self.assertIn(expected_message, messages)
        self.assertEqual(result, expected_result, messages)


class HandshakeTest(CheckTest):
    def test_failed_two_handshakes(self):
        self.assertCheck(
            testcases_webtransport.TestCaseHandshake,
            "quic/resumption/quic-go_quic-go",
            TestResult.FAILED,
            ["Expected exactly 1 handshake. Got: 2"],
        )

    def test_succeeded(self):
        self.assertCheck(
            testcases_webtransport.TestCaseHandshake,
            "webtransport/handshake/webtransport-go_webtransport-go",
            TestResult.SUCCEEDED,
            [],
        )


class TransferDatagramReceiveTest(CheckTest):
    def test_succeeded(self):
        self.assertCheck(
            testcases_webtransport.TestCaseTransferDatagramReceive,
            "webtransport/transfer-datagram-receive/webtransport-go_webtransport-go",
            TestResult.SUCCEEDED,
            [],
        )
