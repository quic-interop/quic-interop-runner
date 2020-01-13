from enum import Enum
from typing import List

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

  def _get_packets(self, f: str) -> List: 
    packets = []
    cap = pyshark.FileCapture(self._filename, display_filter=f)
    for p in cap:
      packets.append(p)
    cap.close()
    return packets
  
  def get_1rtt(self, direction: Direction = Direction.ALL) -> List:
    """ Get all QUIC packets, one or both directions.
    """
    return self._get_packets(self._get_direction_filter(direction) + "quic.header_form==0")

  def get_vnp(self, direction: Direction = Direction.ALL) -> List:
    return self._get_packets(self._get_direction_filter(direction) + "quic.version==0")

  def get_retry(self, direction: Direction = Direction.ALL) -> List:
    return self._get_packets(self._get_direction_filter(direction) + "quic.long.packet_type==Retry")

  def get_initial(self, direction: Direction = Direction.ALL) -> List:
    """ Get all Initial packets.
    Note that this might return coalesced packets. Filter by:
    packet.quic.long_packet_type == "0"
    """
    return self._get_packets(self._get_direction_filter(direction) + "quic.long.packet_type==Initial")

  def get_handshake(self, direction: Direction = Direction.ALL) -> List:
    """ Get all Handshake packets.
    Note that this might return coalesced packets. Filter by:
    packet.quic.long_packet_type == "2"
    """
    return self._get_packets(self._get_direction_filter(direction) + "quic.long.packet_type==Handshake")
