import argparse
import os
import sys

from implementations import IMPLEMENTATIONS

print("Pulling the simulator...")
os.system("docker pull martenseemann/quic-network-simulator")

print("\nPulling the iperf endpoint...")
os.system("docker pull martenseemann/quic-interop-iperf-endpoint")


def get_args():
    parser = argparse.ArgumentParser()
    parser.add_argument("-i", "--implementations", help="implementations to pull")
    return parser.parse_args()


implementations = {}
if get_args().implementations:
    for s in get_args().implementations.split(","):
        if s not in [n for n, _ in IMPLEMENTATIONS.items()]:
            sys.exit("implementation " + s + " not found.")
        implementations[s] = IMPLEMENTATIONS[s]
else:
    implementations = IMPLEMENTATIONS

for name, value in implementations.items():
    print("\nPulling " + name + "...")
    os.system("docker pull " + value["image"])
