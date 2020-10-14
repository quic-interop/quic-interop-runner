import logging
from enum import Enum
from typing import List, Optional

import pyshark

IP4_CLIENT = "193.167.0.100"
IP4_SERVER = "193.167.100.100"
IP6_CLIENT = "fd00:cafe:cafe:0::100"
IP6_SERVER = "fd00:cafe:cafe:100::100"


class Direction(Enum):
    ALL = 0
    FROM_CLIENT = 1
    FROM_SERVER = 2
    INVALID = 3


class PacketType(Enum):
    INITIAL = 1
    HANDSHAKE = 2
    ZERORTT = 3
    RETRY = 4
    ONERTT = 5
    VERSIONNEGOTIATION = 6
    INVALID = 7


WIRESHARK_PACKET_TYPES = {
    PacketType.INITIAL: "0",
    PacketType.ZERORTT: "1",
    PacketType.HANDSHAKE: "2",
    PacketType.RETRY: "3",
}


def get_direction(p) -> Direction:
    if (hasattr(p, "ip") and p.ip.src == IP4_CLIENT) or (
        hasattr(p, "ipv6") and p.ipv6.src == IP6_CLIENT
    ):
        return Direction.FROM_CLIENT

    if (hasattr(p, "ip") and p.ip.src == IP4_SERVER) or (
        hasattr(p, "ipv6") and p.ipv6.src == IP6_SERVER
    ):
        return Direction.FROM_SERVER

    return Direction.INVALID


def get_packet_type(p) -> PacketType:
    if p.quic.header_form == "0":
        return PacketType.ONERTT
    if p.quic.version == "0x00000000":
        return PacketType.VERSIONNEGOTIATION
    for t, num in WIRESHARK_PACKET_TYPES.items():
        if p.quic.long_packet_type == num:
            return t
    return PacketType.INVALID


class TraceAnalyzer:
    _filename = ""

    def __init__(self, filename: str, keylog_file: Optional[str] = None):
        self._filename = filename
        self._keylog_file = keylog_file

    def _get_direction_filter(self, d: Direction) -> str:
        f = "(quic && !icmp) && "
        if d == Direction.FROM_CLIENT:
            return (
                f + "(ip.src==" + IP4_CLIENT + " || ipv6.src==" + IP6_CLIENT + ") && "
            )
        elif d == Direction.FROM_SERVER:
            return (
                f + "(ip.src==" + IP4_SERVER + " || ipv6.src==" + IP6_SERVER + ") && "
            )
        else:
            return f

    def _get_packets(self, f: str) -> List:
        override_prefs = {}
        if self._keylog_file is not None:
            override_prefs["ssl.keylog_file"] = self._keylog_file
        cap = pyshark.FileCapture(
            self._filename,
            display_filter=f,
            override_prefs=override_prefs,
            disable_protocol="http3",  # see https://github.com/marten-seemann/quic-interop-runner/pull/179/
            decode_as={"udp.port==443": "quic"},
        )
        packets = []
        # If the pcap has been cut short in the middle of the packet, pyshark will crash.
        # See https://github.com/KimiNewt/pyshark/issues/390.
        try:
            for p in cap:
                packets.append(p)
            cap.close()
        except Exception as e:
            logging.debug(e)
        return packets

    def get_raw_packets(self, direction: Direction = Direction.ALL) -> List:
        packets = []
        for packet in self._get_packets(self._get_direction_filter(direction) + "quic"):
            packets.append(packet)
        return packets

    def get_1rtt(self, direction: Direction = Direction.ALL) -> List:
        """ Get all QUIC packets, one or both directions. """
        packets = []
        for packet in self._get_packets(
            self._get_direction_filter(direction) + "quic.header_form==0"
        ):
            for layer in packet.layers:
                if layer.layer_name == "quic" and not hasattr(
                    layer, "long_packet_type"
                ):
                    layer.sniff_time = packet.sniff_time
                    packets.append(layer)
        return packets

    def get_vnp(self, direction: Direction = Direction.ALL) -> List:
        return self._get_packets(
            self._get_direction_filter(direction) + "quic.version==0"
        )

    def _get_long_header_packets(
        self, packet_type: PacketType, direction: Direction
    ) -> List:
        packets = []
        for packet in self._get_packets(
            self._get_direction_filter(direction) + "quic.long.packet_type"
        ):
            for layer in packet.layers:
                if (
                    layer.layer_name == "quic"
                    and hasattr(layer, "long_packet_type")
                    and layer.long_packet_type == WIRESHARK_PACKET_TYPES[packet_type]
                ):
                    packets.append(layer)
        return packets

    def get_initial(self, direction: Direction = Direction.ALL) -> List:
        """ Get all Initial packets. """
        return self._get_long_header_packets(PacketType.INITIAL, direction)

    def get_retry(self, direction: Direction = Direction.ALL) -> List:
        """ Get all Retry packets. """
        return self._get_long_header_packets(PacketType.RETRY, direction)

    def get_handshake(self, direction: Direction = Direction.ALL) -> List:
        """ Get all Handshake packets. """
        return self._get_long_header_packets(PacketType.HANDSHAKE, direction)

    def get_0rtt(self) -> List:
        """ Get all 0-RTT packets. """
        return self._get_long_header_packets(PacketType.ZERORTT, Direction.FROM_CLIENT)
