import argparse
import os
import sys

from implementations import get_quic_implementations

print("Pulling the simulator...")
os.system("docker pull martenseemann/quic-network-simulator")

print("\nPulling the iperf endpoint...")
os.system("docker pull martenseemann/quic-interop-iperf-endpoint")


def get_args():
    parser = argparse.ArgumentParser()
    parser.add_argument("-i", "--implementations", help="implementations to pull")
    return parser.parse_args()


impls = get_quic_implementations()
implementations = {}
if get_args().implementations:
    for s in get_args().implementations.split(","):
        if s not in [n for n, _ in impls.items()]:
            sys.exit("implementation " + s + " not found.")
        implementations[s] = impls[s]
else:
    implementations = impls

for name, value in implementations.items():
    print("\nPulling " + name + "...")
    os.system("docker pull " + value["image"])
