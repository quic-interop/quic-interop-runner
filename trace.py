from enum import Enum
from typing import List, Optional

import pyshark


class Direction(Enum):
    ALL = 0
    FROM_CLIENT = 1
    FROM_SERVER = 2


class TraceAnalyzer:
    _filename = ""

    def __init__(self, filename: str, keylog_file: Optional[str] = None):
        self._filename = filename
        self._keylog_file = keylog_file

    def _get_direction_filter(self, d: Direction) -> str:
        f = "(quic && !icmp) && "
        if d == Direction.FROM_CLIENT:
            return f + "ip.src==193.167.0.100 && "
        elif d == Direction.FROM_SERVER:
            return f + "ip.src==193.167.100.100 && "
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
            print(e)
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

    def get_retry(self, direction: Direction = Direction.ALL) -> List:
        packets = []
        for packet in self._get_packets(
            self._get_direction_filter(direction) + "quic.long.packet_type==Retry"
        ):
            for layer in packet.layers:
                if layer.layer_name == "quic":
                    packets.append(layer)
        return packets

    def get_initial(self, direction: Direction = Direction.ALL) -> List:
        """ Get all Initial packets. """
        packets = []
        for packet in self._get_packets(
            self._get_direction_filter(direction) + "quic.long.packet_type"
        ):
            for layer in packet.layers:
                if (
                    layer.layer_name == "quic"
                    and hasattr(layer, "long_packet_type")
                    and layer.long_packet_type == "0"
                ):
                    packets.append(layer)
        return packets

    def get_handshake(self, direction: Direction = Direction.ALL) -> List:
        """ Get all Handshake packets. """
        packets = []
        for packet in self._get_packets(
            self._get_direction_filter(direction) + "quic.long.packet_type"
        ):
            for layer in packet.layers:
                if (
                    layer.layer_name == "quic"
                    and hasattr(layer, "long_packet_type")
                    and layer.long_packet_type == "2"
                ):
                    packets.append(layer)
        return packets

    def get_0rtt(self) -> List:
        """ Get all 0-RTT packets. """
        packets = []
        for packet in self._get_packets(
            self._get_direction_filter(Direction.FROM_CLIENT) + "quic.long.packet_type"
        ):
            for layer in packet.layers:
                if (
                    layer.layer_name == "quic"
                    and hasattr(layer, "long_packet_type")
                    and layer.long_packet_type == "1"
                ):
                    packets.append(layer)
        return packets
