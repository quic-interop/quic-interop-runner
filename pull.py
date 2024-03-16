import argparse
import os
import sys

from implementations import get_quic_implementations, get_webtransport_implementations


def get_args():
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "-p",
        "--protocol",
        default="quic",
        help="quic / webtransport",
    )
    parser.add_argument("-i", "--implementations", help="implementations to pull")
    return parser.parse_args()


args = get_args()
if args.protocol == "quic":
    impls = get_quic_implementations()
elif args.protocol == "webtransport":
    impls = get_webtransport_implementations()
else:
    sys.exit("Unknown protocol: " + args.protocol)
implementations = {}
if args.implementations:
    for s in args.implementations.split(","):
        if s not in [n for n, _ in impls.items()]:
            sys.exit("implementation " + s + " not found.")
        implementations[s] = impls[s]
else:
    implementations = impls

print("Pulling the simulator...")
os.system("docker pull martenseemann/quic-network-simulator")

if args.protocol == "quic":
    print("\nPulling the iperf endpoint...")
    os.system("docker pull martenseemann/quic-interop-iperf-endpoint")

for name, value in implementations.items():
    print("\nPulling " + name + "...")
    os.system("docker pull " + value["image"])
