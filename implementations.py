import json
import os
from enum import Enum

IMPLEMENTATIONS = {}


class Role(Enum):
    BOTH = "both"
    SERVER = "server"
    CLIENT = "client"


with open("implementations.json", "r") as f:
    data = json.load(f)
    for name, val in data.items():
        if name == "linuxquic" and not os.path.exists("/usr/include/linux/quic.h"):
            continue
        IMPLEMENTATIONS[name] = {"image": val["image"], "url": val["url"]}
        role = val["role"]
        if role == "server":
            IMPLEMENTATIONS[name]["role"] = Role.SERVER
        elif role == "client":
            IMPLEMENTATIONS[name]["role"] = Role.CLIENT
        elif role == "both":
            IMPLEMENTATIONS[name]["role"] = Role.BOTH
        else:
            raise Exception("unknown role: " + role)
