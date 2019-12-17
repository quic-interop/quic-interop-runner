from enum import Enum

import pyshark

class Direction(Enum):
  ALL = 0
  FROM_CLIENT = 1
  FROM_SERVER = 2

class TraceAnalyzer:
  _filename = ""

  def __init__(self, filename: str):
    self._filename = filename

  def _get_direction_filter(self, d: Direction) -> str:
    if d == Direction.FROM_CLIENT:
      return "ip.src==193.167.0.100 && "
    elif d == Direction.FROM_SERVER:
      return "ip.src==193.167.100.100 && "
    else:
      return ""

  def get_1rtt(self, direction: Direction = Direction.ALL) -> pyshark.FileCapture:
    """ Get all QUIC packets, one or both directions.
    """
    f = self._get_direction_filter(direction) + "quic.header_form==0"
    return pyshark.FileCapture(self._filename, display_filter=f)

  def get_vnp(self, direction: Direction = Direction.ALL) -> pyshark.FileCapture:
    f = self._get_direction_filter(direction) + "quic.version==0"
    return pyshark.FileCapture(self._filename, display_filter=f)

  def get_retry(self, direction: Direction = Direction.ALL) -> pyshark.FileCapture:
    f = self._get_direction_filter(direction) + "quic.long.packet_type==Retry"
    return pyshark.FileCapture(self._filename, display_filter=f)

  def get_initial(self, direction: Direction = Direction.ALL) -> pyshark.FileCapture:
    """ Get all Initial packets.
    Note that this might return coalesced packets. Filter by:
    packet.quic.long_packet_type == "0"
    """
    f = self._get_direction_filter(direction) + "quic.long.packet_type==Initial"
    return pyshark.FileCapture(self._filename, display_filter=f)

  def get_handshake(self, direction: Direction = Direction.ALL) -> pyshark.FileCapture:
    """ Get all Initial packets.
    Note that this might return coalesced packets. Filter by:
    packet.quic.long_packet_type == "2"
    """
    f = self._get_direction_filter(direction) + "quic.long.packet_type==Handshake"
    return pyshark.FileCapture(self._filename, display_filter=f)
