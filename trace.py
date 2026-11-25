import datetime
import functools
import json
import logging
import subprocess
from enum import Enum
from typing import Dict, List, Optional, Sequence, Tuple, Union

IP4_CLIENT = "193.167.0.100"
IP4_SERVER = "193.167.100.100"
IP6_CLIENT = "fd00:cafe:cafe:0::100"
IP6_SERVER = "fd00:cafe:cafe:100::100"


QUIC_V2 = 0x6B3343CF

# The values of integer, boolean and byte fields are converted, the others are
# kept as tshark prints them.
Value = Union[bool, bytes, int, str]


class Fields:
    """
    The fields of a frame or of a QUIC packet, by their tshark names.

    A field can have several values, in the order tshark prints them:

    - `fields["quic.scid"]` returns the first value, and raises KeyError if
      tshark did not print the field.
    - `fields.get("quic.dcid")` returns the first value, or None if the field is
      absent, or the default given as second argument.
    - `fields.get_all("tls.handshake.ciphersuite")` returns all the values, or
      an empty list.
    - `"quic.token" in fields` tells whether tshark printed the field.
    """

    def __init__(self) -> None:
        self._values: Dict[str, List[Value]] = {}

    def __contains__(self, name: str) -> bool:
        return name in self._values

    def __getitem__(self, name: str) -> Value:
        return self._values[name][0]

    def __repr__(self) -> str:
        return repr(self._values)

    def add(self, name: str, value: Value) -> None:
        self._values.setdefault(name, []).append(value)

    def copy(self) -> "Fields":
        fields = Fields()
        fields._values = {name: list(values) for name, values in self._values.items()}
        return fields

    def get(self, name: str, default: Optional[Value] = None) -> Optional[Value]:
        """Get the first value of a field, or the default if it is absent."""
        values = self._values.get(name)
        return values[0] if values else default

    def get_all(self, name: str) -> List[Value]:
        """Get all the values of a field, none if it is absent."""
        return self._values.get(name, [])


INTEGER_TYPES = {
    "FT_FRAMENUM",
    "FT_INT8",
    "FT_INT16",
    "FT_INT24",
    "FT_INT32",
    "FT_INT40",
    "FT_INT48",
    "FT_INT56",
    "FT_INT64",
    "FT_UINT8",
    "FT_UINT16",
    "FT_UINT24",
    "FT_UINT32",
    "FT_UINT40",
    "FT_UINT48",
    "FT_UINT56",
    "FT_UINT64",
}


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
    PacketType.INITIAL: 0,
    PacketType.ZERORTT: 1,
    PacketType.HANDSHAKE: 2,
    PacketType.RETRY: 3,
}


WIRESHARK_PACKET_TYPES_V2 = {
    PacketType.INITIAL: 1,
    PacketType.ZERORTT: 2,
    PacketType.HANDSHAKE: 3,
    PacketType.RETRY: 0,
}


def get_direction(p: Fields) -> Direction:
    if p.get("ip.src") == IP4_CLIENT or (p.get("ipv6.src") == IP6_CLIENT):
        return Direction.FROM_CLIENT

    if p.get("ip.src") == IP4_SERVER or (p.get("ipv6.src") == IP6_SERVER):
        return Direction.FROM_SERVER

    return Direction.INVALID


def get_packet_type(p: Fields) -> PacketType:
    # A malformed packet has no fields.
    if "quic.header_form" not in p:
        return PacketType.INVALID
    if p["quic.header_form"] == 0:
        return PacketType.ONERTT
    if p["quic.version"] == 0:
        return PacketType.VERSIONNEGOTIATION
    if p["quic.version"] == QUIC_V2:
        for t, num in WIRESHARK_PACKET_TYPES_V2.items():
            if p.get("quic.long.packet_type_v2") == num:
                return t
        return PacketType.INVALID
    for t, num in WIRESHARK_PACKET_TYPES.items():
        if p.get("quic.long.packet_type") == num:
            return t
    return PacketType.INVALID


@functools.lru_cache(maxsize=None)
def _field_types() -> Dict[str, str]:
    """Get the type of every field tshark knows, such as "FT_UINT8"."""
    output = subprocess.run(["tshark", "-G", "fields"], stdout=subprocess.PIPE).stdout
    types = {}
    for line in output.decode("utf-8", errors="replace").splitlines():
        columns = line.split("\t")
        if columns[0] == "F" and len(columns) > 3:
            types[columns[2]] = columns[3]
    # Without the types, no value would be converted, and the checks would fail
    # for misleading reasons.
    if not types:
        raise RuntimeError("tshark did not print the types of its fields")
    return types


def _convert(name: str, value: str) -> Value:
    """
    Convert a value printed by tshark according to the type of its field.

    tshark prints byte fields with colons in JSON, and without them otherwise,
    and booleans as "1" or "True" depending on the output format.
    """
    field_type = _field_types().get(name)
    try:
        if field_type in INTEGER_TYPES:
            return int(value, 16) if value.startswith("0x") else int(value)
        if field_type == "FT_BOOLEAN":
            return value in ["1", "True"]
        if field_type == "FT_BYTES":
            return bytes.fromhex(value.replace(":", ""))
    except ValueError:
        # Keep the value as printed, for example a named value.
        pass
    return value


def _flatten(tree: dict, fields: Fields) -> Fields:
    """
    Add the values of the fields in a tree of tshark's JSON output to `fields`.

    Fields are found at any depth, for example the TLS fields under the CRYPTO
    frames, or expert information, whose value is empty.
    """
    for name, value in tree.items():
        for v in value if isinstance(value, list) else [value]:
            if isinstance(v, dict):
                _flatten(v, fields)
            else:
                fields.add(name, _convert(name, v))
    return fields


class TraceAnalyzer:
    _filename = ""

    def __init__(self, filename: str, keylog_file: Optional[str] = None):
        self._filename = filename
        self._keylog_file = keylog_file

    def _get_direction_filter(self, d: Direction) -> str:
        # ICMP errors quote the packet that caused them, exclude them so that the
        # quoted addresses are not mistaken for those of the packet.
        f = "(quic && !icmp && !icmpv6) && "
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

    def _run_tshark(self, display_filter: str, output: List[str]) -> str:
        cmd = ["tshark", "-n", "-r", self._filename]
        if self._keylog_file is not None:
            cmd += ["-o", "tls.keylog_file:" + self._keylog_file]
        cmd += [
            "--disable-protocol",
            "http3",  # see https://github.com/quic-interop/quic-interop-runner/pull/179
            "-d",
            "udp.port==443,quic",
            "-Y",
            display_filter,
        ] + output
        r = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        # If the pcap has been cut short in the middle of a packet, tshark still
        # prints the packets before it. Without any output, report why, as the
        # checks would otherwise fail as if the capture had no packets.
        if r.returncode != 0:
            logging.log(
                logging.DEBUG if r.stdout else logging.INFO,
                "tshark: %s",
                r.stderr.decode("utf-8", errors="replace"),
            )
        return r.stdout.decode("utf-8", errors="replace")

    def _get_frames(self, display_filter: str) -> List[dict]:
        """
        Get the layers of each matching frame, as printed by tshark in JSON.

        Coalesced QUIC packets are a list of "quic" layers.
        """
        output = self._run_tshark(display_filter, ["-T", "json", "--no-duplicate-keys"])
        # The output of a capture cut short in the middle of a packet is not valid
        # JSON, read the frames one by one until then.
        frames = []
        decoder = json.JSONDecoder()
        position = output.find("{")
        while position != -1:
            try:
                frame, position = decoder.raw_decode(output, position)
            except json.JSONDecodeError:
                break
            frames.append(frame["_source"]["layers"])
            position = output.find("{", position)

        if self._keylog_file is not None:
            for layers in frames:
                if "quic.decryption_failed" in _flatten(layers, Fields()):
                    logging.info("At least one QUIC packet could not be decrypted")
                    logging.debug(layers)
                    break
        return frames

    def _get_packets(self, display_filter: str) -> List[Fields]:
        """
        Get the fields of each QUIC packet in the matching frames, along with the
        fields of the frame they were sent in, such as the IP addresses.
        """
        packets = []
        for layers in self._get_frames(display_filter):
            frame_fields = _flatten(
                {name: layer for name, layer in layers.items() if name != "quic"},
                Fields(),
            )
            quic = layers["quic"]
            for packet in quic if isinstance(quic, list) else [quic]:
                # A malformed packet has no fields, only the protocol name.
                if not isinstance(packet, dict):
                    continue
                packets.append(_flatten(packet, frame_fields.copy()))
        return packets

    def get_raw_packets(self, direction: Direction = Direction.ALL) -> List[Fields]:
        """
        Get the fields of each frame with QUIC packets, one or both directions.

        The fields of coalesced QUIC packets are in the order of the packets.
        """
        return [
            _flatten(layers, Fields())
            for layers in self._get_frames(
                self._get_direction_filter(direction) + "quic"
            )
        ]

    def get_1rtt(self, direction: Direction = Direction.ALL) -> List[Fields]:
        """Get all 1-RTT packets, one or both directions."""
        return [
            packet
            for packet in self._get_packets(
                self._get_direction_filter(direction) + "quic.header_form==0"
            )
            if "quic.long.packet_type" not in packet
            and "quic.long.packet_type_v2" not in packet
        ]

    def get_fields(
        self,
        *,
        fields: Sequence[str],
        direction: Direction = Direction.ALL,
        display_filter: str = "quic",
    ) -> List[Fields]:
        """
        Get the values of some fields for each matching frame, one or both directions.

        The values of different fields are not aligned when a frame contains
        coalesced QUIC packets.

        Only the requested fields are read, which is faster than reading all of
        them for large captures. Values are converted as in the other methods.
        They are split on commas, so this is not suitable for free-text string
        fields.
        """
        output = ["-T", "fields", "-E", "separator=/t", "-E", "occurrence=a"]
        output += ["-E", "aggregator=,"]
        for field in fields:
            output += ["-e", field]
        frames = []
        for line in self._run_tshark(
            self._get_direction_filter(direction) + display_filter, output
        ).splitlines():
            frame = Fields()
            for field, value in zip(fields, line.split("\t")):
                if value:
                    for v in value.split(","):
                        frame.add(field, _convert(field, v))
            frames.append(frame)
        return frames

    def get_1rtt_sniff_times(
        self, direction: Direction = Direction.ALL
    ) -> Optional[Tuple[datetime.datetime, datetime.datetime]]:
        """
        Get the sniff times of the first and last 1-RTT packets, one or both directions.
        """
        frames = self.get_fields(
            fields=["frame.time_epoch"],
            direction=direction,
            display_filter="quic.header_form==0",
        )
        if not frames:
            return None
        return (
            datetime.datetime.fromtimestamp(float(frames[0]["frame.time_epoch"])),
            datetime.datetime.fromtimestamp(float(frames[-1]["frame.time_epoch"])),
        )

    def get_vnp(self, direction: Direction = Direction.ALL) -> List[Fields]:
        """Get all Version Negotiation packets, one or both directions."""
        return self._get_packets(
            self._get_direction_filter(direction) + "quic.version==0"
        )

    def _get_long_header_packets(
        self, packet_type: PacketType, direction: Direction
    ) -> List[Fields]:
        packets = []
        for packet in self._get_packets(
            self._get_direction_filter(direction)
            + "(quic.long.packet_type || quic.long.packet_type_v2)"
        ):
            if (
                packet.get("quic.long.packet_type")
                == WIRESHARK_PACKET_TYPES[packet_type]
                or packet.get("quic.long.packet_type_v2")
                == WIRESHARK_PACKET_TYPES_V2[packet_type]
            ):
                packets.append(packet)
        return packets

    def get_initial(self, direction: Direction = Direction.ALL) -> List[Fields]:
        """Get all Initial packets."""
        return self._get_long_header_packets(PacketType.INITIAL, direction)

    def get_retry(self, direction: Direction = Direction.ALL) -> List[Fields]:
        """Get all Retry packets."""
        return self._get_long_header_packets(PacketType.RETRY, direction)

    def get_handshake(self, direction: Direction = Direction.ALL) -> List[Fields]:
        """Get all Handshake packets."""
        return self._get_long_header_packets(PacketType.HANDSHAKE, direction)

    def get_0rtt(self) -> List[Fields]:
        """Get all 0-RTT packets."""
        return self._get_long_header_packets(PacketType.ZERORTT, Direction.FROM_CLIENT)
