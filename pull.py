import os
from implementations import IMPLEMENTATIONS

print("Pulling the simulator...")
os.system("docker pull martenseemann/quic-network-simulator")

for name in IMPLEMENTATIONS:
  print("\nPulling " + name + "...")
  os.system("docker pull " + IMPLEMENTATIONS[name])
