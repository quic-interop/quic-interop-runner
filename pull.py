#!/usr/bin/env python3

import argparse
import os
import sys

from implementations import IMPLEMENTATIONS

SIMULATOR_IMAGE = "martenseemann/quic-network-simulator"
IPERF_IMAGE = "martenseemann/quic-interop-iperf-endpoint"


def get_args():
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "-i",
        "--implementations",
        nargs="*",
        choices=set(IMPLEMENTATIONS.keys()),
        help="implementations to pull",
    )

    return parser.parse_args()


def docker_pull(name: str, image: str):
    """Pull docker image."""
    print(f"Pulling {name}...")
    os.system(f"docker pull {image}")
    print()


def main():
    args = get_args()
    implementations = {}

    if args.implementations:
        for impl in args.implementations:
            implementations[impl] = IMPLEMENTATIONS[impl]
    else:
        implementations = IMPLEMENTATIONS

    docker_pull("the simulator", SIMULATOR_IMAGE)
    docker_pull("the iperf endpoint", IPERF_IMAGE)

    for name, value in implementations.items():
        docker_pull(name, value["image"])


if __name__ == "__main__":
    main()
