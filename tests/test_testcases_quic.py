import os
import shutil
import tempfile
import unittest

import testcases_quic
from result import TestResult

DATA_DIR = os.path.join(os.path.dirname(__file__), "data")


class CheckTest(unittest.TestCase):
    """
    Run the check of a test case on the captures of a past interop run.

    The captures are taken from tests/data/quic/<test case>/<server>_<client>. The
    files the test case generates are copied to the client's download directory,
    so that the check only depends on the captures.

    Some tests run a check on the captures of another test case, to exercise its
    failures.
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
        # Some test cases do not transfer any file, and return an empty name.
        for name in filter(None, test.get_paths_raw()):
            shutil.copy(
                os.path.join(test.server_www_dir(), name), test.client_download_dir()
            )

        with self.assertLogs(level="DEBUG") as logs:
            result = test.check()
        return result, "\n".join(record.getMessage() for record in logs.records)

    def assertCheck(self, test_class, fixture, expected_result, expected_messages):
        result, messages = self.run_check(test_class, fixture)
        for expected_message in expected_messages:
            self.assertIn(expected_message, messages)
        self.assertEqual(result, expected_result, messages)


class VersionNegotiationTest(CheckTest):
    def test_failed_no_version_negotiation(self):
        self.assertCheck(
            testcases_quic.TestCaseVersionNegotiation,
            "quic/handshake/quic-go_quic-go",
            TestResult.FAILED,
            ["Didn't find a Version Negotiation Packet with matching SCID."],
        )

    def test_succeeded(self):
        # The client's Initial packets use a reserved version.
        self.assertCheck(
            testcases_quic.TestCaseVersionNegotiation,
            "quic/versionnegotiation/quic-go_quic-go",
            TestResult.SUCCEEDED,
            [],
        )


class HandshakeTest(CheckTest):
    def test_failed_retry(self):
        self.assertCheck(
            testcases_quic.TestCaseHandshake,
            "quic/retry/quic-go_quic-go",
            TestResult.FAILED,
            ["Didn't expect a Retry to be sent."],
        )

    def test_succeeded(self):
        self.assertCheck(
            testcases_quic.TestCaseHandshake,
            "quic/handshake/quic-go_quic-go",
            TestResult.SUCCEEDED,
            [],
        )


class TransferTest(CheckTest):
    def test_failed_two_handshakes(self):
        self.assertCheck(
            testcases_quic.TestCaseTransfer,
            "quic/resumption/quic-go_quic-go",
            TestResult.FAILED,
            ["Expected exactly 1 handshake. Got: 2"],
        )


class LongRTTTest(CheckTest):
    def test_failed_no_retransmission(self):
        self.assertCheck(
            testcases_quic.TestCaseLongRTT,
            "quic/handshake/quic-go_quic-go",
            TestResult.FAILED,
            ["Expected at least 2 ClientHellos. Got: 1"],
        )

    def test_succeeded(self):
        self.assertCheck(
            testcases_quic.TestCaseLongRTT,
            "quic/longrtt/quic-go_quic-go",
            TestResult.SUCCEEDED,
            ["Client sent 7 ClientHellos."],
        )


class ChaCha20Test(CheckTest):
    def test_failed_other_cipher_suite(self):
        self.assertCheck(
            testcases_quic.TestCaseChaCha20,
            "quic/handshake/quic-go_quic-go",
            TestResult.FAILED,
            ["Expected only ChaCha20 cipher suite to be offered. Got: {'0x1301'}"],
        )

    def test_succeeded(self):
        self.assertCheck(
            testcases_quic.TestCaseChaCha20,
            "quic/chacha20/quic-go_quic-go",
            TestResult.SUCCEEDED,
            [],
        )


class MultiplexingTest(CheckTest):
    def test_succeeded(self):
        self.assertCheck(
            testcases_quic.TestCaseMultiplexing,
            "quic/multiplexing/quic-go_quic-go",
            TestResult.SUCCEEDED,
            ["Server set bidirectional stream limit: 100"],
        )


class RetryTest(CheckTest):
    def test_failed_no_retry(self):
        self.assertCheck(
            testcases_quic.TestCaseRetry,
            "quic/handshake/quic-go_quic-go",
            TestResult.FAILED,
            ["Didn't find any Retry packets."],
        )

    def test_succeeded(self):
        self.assertCheck(
            testcases_quic.TestCaseRetry,
            "quic/retry/quic-go_quic-go",
            TestResult.SUCCEEDED,
            [
                "Check of Retry succeeded. Token used: "
                "c6b3d68590922ea51d5729681e2407563e4a290e6fe4e0b2f20ef528f11da3f2"
                "ae11b7da4b4da0198788a3ae1fba79e1463e56385e7a65848a0ef3db2a36d91f"
                "8b841e420d7d002a4ce8dbe9964850a5c1"
            ],
        )


class ResumptionTest(CheckTest):
    def test_failed_certificate_in_second_handshake(self):
        self.assertCheck(
            testcases_quic.TestCaseResumption,
            "quic/resumption/quic-go_xquic",
            TestResult.FAILED,
            ["Server sent a Certificate message in the second handshake."],
        )

    def test_failed_one_handshake(self):
        self.assertCheck(
            testcases_quic.TestCaseResumption,
            "quic/handshake/quic-go_quic-go",
            TestResult.FAILED,
            ["Expected exactly 2 handshake. Got: 1"],
        )

    def test_succeeded(self):
        self.assertCheck(
            testcases_quic.TestCaseResumption,
            "quic/resumption/quic-go_quic-go",
            TestResult.SUCCEEDED,
            [],
        )


class ZeroRTTTest(CheckTest):
    def test_failed_one_handshake(self):
        self.assertCheck(
            testcases_quic.TestCaseZeroRTT,
            "quic/handshake/quic-go_quic-go",
            TestResult.FAILED,
            ["Expected exactly 2 handshakes. Got: 1"],
        )

    def test_failed_too_much_1rtt_data(self):
        self.assertCheck(
            testcases_quic.TestCaseZeroRTT,
            "quic/zerortt/ngtcp2_neqo",
            TestResult.FAILED,
            [
                "0-RTT size: 20723",
                "1-RTT size: 11788",
                "Client sent too much data in 1-RTT packets.",
            ],
        )

    def test_succeeded(self):
        self.assertCheck(
            testcases_quic.TestCaseZeroRTT,
            "quic/zerortt/quic-go_quic-go",
            TestResult.SUCCEEDED,
            ["0-RTT size: 10429", "1-RTT size: 594"],
        )


class KeyUpdateTest(CheckTest):
    def test_failed_no_key_update(self):
        self.assertCheck(
            testcases_quic.TestCaseKeyUpdate,
            "quic/keyupdate/s2n-quic_xquic",
            TestResult.FAILED,
            [
                "Client sent 1 key phase 0 and 0 key phase 1 packets.",
                "Server sent 17 key phase 0 and 0 key phase 1 packets.",
                "Expected to see packets sent with key phase 1 from both client and server.",
            ],
        )

    def test_succeeded(self):
        self.assertCheck(
            testcases_quic.TestCaseKeyUpdate,
            "quic/keyupdate/go-x-net_msquic",
            TestResult.SUCCEEDED,
            [
                "Client sent 33 key phase 0 and 3 key phase 1 packets.",
                "Server sent 3 key phase 0 and 8 key phase 1 packets.",
            ],
        )


class ECNTest(CheckTest):
    def test_failed_no_ack_ecn(self):
        self.assertCheck(
            testcases_quic.TestCaseECN,
            "quic/handshake/quic-go_quic-go",
            TestResult.FAILED,
            ["Server did not send any ACK-ECN frames"],
        )

    def test_succeeded(self):
        # The number of packets with each ECN codepoint sent by the client, then
        # by the server.
        self.assertCheck(
            testcases_quic.TestCaseECN,
            "quic/ecn/picoquic_picoquic",
            TestResult.SUCCEEDED,
            ["0 0\n1 44\n2 0\n3 0", "0 0\n1 117\n2 0\n3 0"],
        )


class AmplificationLimitTest(CheckTest):
    def test_failed_limit_violated(self):
        self.assertCheck(
            testcases_quic.TestCaseAmplificationLimit,
            "quic/amplificationlimit/picoquic_quic-go",
            TestResult.FAILED,
            [
                "Server sent 9966 bytes in Handshake CRYPTO frames.",
                "Received a 650 byte Handshake packet from the server. Total: 10709",
                "Server violated the amplification limit.",
            ],
        )

    def test_failed_small_certificate_chain(self):
        self.assertCheck(
            testcases_quic.TestCaseAmplificationLimit,
            "quic/handshake/quic-go_quic-go",
            TestResult.FAILED,
            [
                "Server sent too little Handshake CRYPTO data (714 bytes). "
                "Not using the provided cert chain?"
            ],
        )

    def test_succeeded(self):
        self.assertCheck(
            testcases_quic.TestCaseAmplificationLimit,
            "quic/amplificationlimit/quic-go_quic-go",
            TestResult.SUCCEEDED,
            [
                "Server sent 9962 bytes in Handshake CRYPTO frames.",
                "Received a 1280 byte Handshake packet from the server. Total: 7717",
                "Server violated the amplification limit, but stayed within 3-4x "
                "amplification. Letting it slide.",
            ],
        )


class HandshakeLossTest(CheckTest):
    def test_failed_one_handshake(self):
        self.assertCheck(
            testcases_quic.TestCaseHandshakeLoss,
            "quic/handshakeloss/quic-go_mvfst",
            TestResult.FAILED,
            ["Expected 50 handshakes. Got: 1"],
        )


class IPv6Test(CheckTest):
    def test_failed_ipv4(self):
        self.assertCheck(
            testcases_quic.TestCaseIPv6,
            "quic/handshake/quic-go_quic-go",
            TestResult.FAILED,
            ["Packet trace contains 5 IPv4 packets."],
        )

    def test_succeeded(self):
        self.assertCheck(
            testcases_quic.TestCaseIPv6,
            "quic/ipv6/quic-go_quic-go",
            TestResult.SUCCEEDED,
            [],
        )


class V2Test(CheckTest):
    def test_failed_server_initial_v1(self):
        self.assertCheck(
            testcases_quic.TestCaseV2,
            "quic/v2/aioquic_msquic",
            TestResult.FAILED,
            ["Wrong version in server Initial. Expected 0x6b3343cf, got {'0x1'}"],
        )

    def test_succeeded(self):
        self.assertCheck(
            testcases_quic.TestCaseV2,
            "quic/v2/aioquic_aioquic",
            TestResult.SUCCEEDED,
            [],
        )


class PortRebindingTest(CheckTest):
    def test_failed_no_path_challenge(self):
        self.assertCheck(
            testcases_quic.TestCasePortRebinding,
            "quic/rebind-port/quiche_neqo",
            TestResult.FAILED,
            [
                "First server packet on new path "
                "(('193.167.100.100', 443), ('193.167.0.100', 57607)) "
                "did not contain a PATH_CHALLENGE frame"
            ],
        )

    def test_failed_single_path(self):
        self.assertCheck(
            testcases_quic.TestCasePortRebinding,
            "quic/rebind-port/go-x-net_xquic",
            TestResult.FAILED,
            ["Server saw only a single path in use; test broken?"],
        )

    def test_succeeded(self):
        self.assertCheck(
            testcases_quic.TestCasePortRebinding,
            "quic/rebind-port/quic-go_quic-go",
            TestResult.SUCCEEDED,
            # The paths are logged as a set, in no particular order.
            [
                "Server saw these paths used:",
                "(('193.167.100.100', 443), ('193.167.0.100', 34060))",
                "(('193.167.100.100', 443), ('193.167.0.100', 57607))",
                "(('193.167.100.100', 443), ('193.167.0.100', 59022))",
            ],
        )


class AddressRebindingTest(CheckTest):
    def test_failed_no_path_response(self):
        self.assertCheck(
            testcases_quic.TestCaseAddressRebinding,
            "quic/rebind-addr/msquic_aioquic",
            TestResult.FAILED,
            ["PATH_CHALLENGE without a PATH_RESPONSE"],
        )

    def test_failed_single_address(self):
        self.assertCheck(
            testcases_quic.TestCaseAddressRebinding,
            "quic/rebind-addr/msquic_quiche",
            TestResult.FAILED,
            ["Server saw only a single client IP address in use; test broken?"],
        )

    def test_succeeded(self):
        self.assertCheck(
            testcases_quic.TestCaseAddressRebinding,
            "quic/rebind-addr/quic-go_quic-go",
            TestResult.SUCCEEDED,
            # The addresses and paths are logged as sets, in no particular order.
            [
                "Server saw these client addresses:",
                "Server saw these paths used:",
                "(('193.167.100.100', 443), ('193.167.0.71', 39968))",
                "(('193.167.100.100', 443), ('193.167.0.100', 34410))",
                "(('193.167.100.100', 443), ('193.167.0.224', 59022))",
            ],
        )

    def test_unsupported_no_keylog(self):
        self.assertCheck(
            testcases_quic.TestCaseAddressRebinding,
            "quic/rebind-addr/kwik_quiche",
            TestResult.UNSUPPORTED,
            ["Can't check test result. SSLKEYLOG required."],
        )


class ConnectionMigrationTest(CheckTest):
    def test_failed_icmpv6_error(self):
        # The client sends an ICMPv6 port unreachable error quoting a server
        # packet, which must not be mistaken for a server packet on a new path.
        self.assertCheck(
            testcases_quic.TestCaseConnectionMigration,
            "quic/connectionmigration/s2n-quic_ngtcp2",
            TestResult.FAILED,
            ["Server saw only a single path in use; test broken?"],
        )

    def test_succeeded(self):
        self.assertCheck(
            testcases_quic.TestCaseConnectionMigration,
            "quic/connectionmigration/picoquic_aioquic",
            TestResult.SUCCEEDED,
            [
                "during active migration to "
                "(('fd00:cafe:cafe::100', 50907), ('fd00:cafe:cafe:100::100', 4433))",
            ],
        )
