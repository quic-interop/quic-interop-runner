import os
from implementations import IMPLEMENTATIONS

print("Pulling the simulator...")
os.system("docker pull martenseemann/quic-network-simulator")

print("\nPulling the iperf endpoint...")
os.system("docker pull martenseemann/quic-interop-iperf-endpoint")

for name, value in IMPLEMENTATIONS.items():
  print("\nPulling " + name + "...")
  os.system("docker pull " + value["url"])
