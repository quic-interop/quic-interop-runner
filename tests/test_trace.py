import os
import shutil
import tempfile
import unittest

from trace import Direction, Fields, PacketType, TraceAnalyzer, get_packet_type

DATA_DIR = os.path.join(os.path.dirname(__file__), "data")


def copy_fixture(test, fixture):
    """
    Copy the logs of a fixture to a temporary directory, removed after the test.

    On some CI runners tshark cannot read files outside the temporary directory.
    """
    tmp = tempfile.TemporaryDirectory()
    test.addCleanup(tmp.cleanup)
    shutil.copytree(os.path.join(DATA_DIR, fixture), tmp.name, dirs_exist_ok=True)
    return tmp.name


def open_trace(test, fixture, name):
    fixture_dir = copy_fixture(test, fixture)
    return TraceAnalyzer(
        os.path.join(fixture_dir, name), os.path.join(fixture_dir, "client_keys.log")
    )


class CoalescedPacketsTest(unittest.TestCase):
    """
    The server coalesces Initial and Handshake packets in the same datagram, and
    the trace ends with ICMP errors quoting QUIC packets.
    """

    def setUp(self):
        self.trace = open_trace(
            self, "quic/amplificationlimit/picoquic_quic-go", "trace_node_right.pcap"
        )

    def test_1rtt(self):
        self.assertEqual(len(self.trace.get_1rtt(Direction.FROM_CLIENT)), 6)
        self.assertEqual(len(self.trace.get_1rtt(Direction.FROM_SERVER)), 23)

    def test_1rtt_sniff_times(self):
        # The ICMP errors at the end of the trace are not 1-RTT packets.
        for direction, expected in [
            (Direction.ALL, (1795567262.327231222, 1795567262.401517911)),
            (Direction.FROM_CLIENT, (1795567262.366611286, 1795567262.401460786)),
            (Direction.FROM_SERVER, (1795567262.327231222, 1795567262.401517911)),
        ]:
            with self.subTest(direction=direction):
                first, last = self.trace.get_1rtt_sniff_times(direction)
                self.assertAlmostEqual(first.timestamp(), expected[0], delta=1e-5)
                self.assertAlmostEqual(last.timestamp(), expected[1], delta=1e-5)

    def test_handshake(self):
        self.assertEqual(len(self.trace.get_handshake(Direction.FROM_CLIENT)), 9)
        self.assertEqual(len(self.trace.get_handshake(Direction.FROM_SERVER)), 9)

    def test_initial(self):
        self.assertEqual(len(self.trace.get_initial(Direction.FROM_CLIENT)), 3)
        self.assertEqual(len(self.trace.get_initial(Direction.FROM_SERVER)), 2)

    def test_retry_and_version_negotiation(self):
        self.assertEqual(len(self.trace.get_retry()), 0)
        self.assertEqual(len(self.trace.get_vnp()), 0)


class TruncatedTraceTest(unittest.TestCase):
    """
    The capture is cut short in the middle of a packet, as when the simulator
    is killed before it finishes writing it.
    """

    def setUp(self):
        fixture_dir = copy_fixture(self, "quic/amplificationlimit/picoquic_quic-go")
        trace = os.path.join(fixture_dir, "trace_node_right.pcap")
        with open(trace, "r+b") as f:
            f.truncate(os.path.getsize(trace) - 100)
        self.trace = TraceAnalyzer(trace, os.path.join(fixture_dir, "client_keys.log"))

    def test_1rtt_sniff_times(self):
        first, last = self.trace.get_1rtt_sniff_times(Direction.ALL)
        self.assertAlmostEqual(first.timestamp(), 1795567262.327231222, delta=1e-5)
        self.assertAlmostEqual(last.timestamp(), 1795567262.401517911, delta=1e-5)

    def test_initial(self):
        self.assertEqual(len(self.trace.get_initial(Direction.FROM_SERVER)), 2)


class MalformedPacketTest(unittest.TestCase):
    """
    The last datagram holds an Initial packet followed by bytes that Wireshark
    dissects as a malformed coalesced packet, without any field.
    """

    def setUp(self):
        self.trace = open_trace(
            self, "quic/handshakeloss/aioquic_aioquic", "trace_node_right.pcap"
        )

    def test_handshake(self):
        self.assertEqual(len(self.trace.get_handshake(Direction.FROM_SERVER)), 1)

    def test_initial(self):
        self.assertEqual(len(self.trace.get_initial(Direction.FROM_SERVER)), 4)


class PacketTypeTest(unittest.TestCase):
    def test_malformed(self):
        # A malformed packet has no fields.
        self.assertEqual(get_packet_type(Fields()), PacketType.INVALID)


class ICMPv6Test(unittest.TestCase):
    """
    The client sends an ICMPv6 port unreachable error quoting a server packet,
    which is not a QUIC packet of either endpoint.
    """

    def setUp(self):
        self.trace = open_trace(
            self, "quic/connectionmigration/s2n-quic_ngtcp2", "trace_node_right.pcap"
        )

    def test_raw_packets(self):
        self.assertEqual(len(self.trace.get_raw_packets(Direction.FROM_CLIENT)), 17)
        self.assertEqual(len(self.trace.get_raw_packets(Direction.FROM_SERVER)), 29)
