import argparse
import json
import sys
from enum import Enum
from typing import Dict


class Role(Enum):
    BOTH = "both"
    SERVER = "server"
    CLIENT = "client"


def get_quic_implementations() -> Dict[str, Dict[str, str | Role]]:
    return get_implementations("implementations_quic.json")


def get_webtransport_implementations() -> Dict[str, Dict[str, str | Role]]:
    return get_implementations("implementations_webtransport.json")


def get_implementations(filename: str) -> Dict[str, Dict[str, str | Role]]:
    implementations: Dict[str, Dict[str, str | Role]] = {}
    with open(filename, "r") as f:
        data = json.load(f)
        for name, val in data.items():
            implementations[name] = {"image": val["image"], "url": val["url"]}
            role = val["role"]
            if role == "server":
                implementations[name]["role"] = Role.SERVER
            elif role == "client":
                implementations[name]["role"] = Role.CLIENT
            elif role == "both":
                implementations[name]["role"] = Role.BOTH
            else:
                raise Exception("unknown role: " + role)
        return implementations


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "-p",
        "--protocol",
        default="quic",
        help="quic / webtransport",
    )
    args = parser.parse_args()

    if args.protocol == "quic":
        filename = "implementations_quic.json"
        impls = get_quic_implementations()
    elif args.protocol == "webtransport":
        filename = "implementations_webtransport.json"
        impls = get_webtransport_implementations()
    else:
        sys.exit("Unknown protocol: " + args.protocol)

    print(f"{filename}:")
    for name, data in impls.items():
        print(f"  - {name} ({data['role'].value})")
