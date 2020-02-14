#!/usr/bin/env python3

import argparse
import logging
import sys
from typing import List

import testcases
from implementations import IMPLEMENTATIONS
from interop import InteropRunner
from testcases import MEASUREMENTS, TESTCASES


def get_args():
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "-d",
        "--debug",
        action="store_const",
        const=True,
        default=False,
        help="turn on debug logs",
    )
    parser.add_argument(
        "-s", "--server", help="server implementations (comma-separated)"
    )
    parser.add_argument(
        "-c", "--client", help="client implementations (comma-separated)"
    )
    parser.add_argument("-t", "--test", help="test cases (comma-separatated)")
    parser.add_argument("-m", "--measurement", help="measurements (comma-separatated)")
    parser.add_argument(
        "-r",
        "--replace",
        help="replace path of implementation. Example: -r myquicimpl=dockertagname",
    )
    parser.add_argument("-j", "--json", help="output the matrix to file in json format")
    return parser.parse_args()


logger = logging.getLogger()
logger.setLevel(logging.DEBUG)
console = logging.StreamHandler(stream=sys.stderr)
if get_args().debug:
    console.setLevel(logging.DEBUG)
else:
    console.setLevel(logging.INFO)
logger.addHandler(console)

implementations = {name: value["url"] for name, value in IMPLEMENTATIONS.items()}
client_implementations = [
    name
    for name, value in IMPLEMENTATIONS.items()
    if value["role"] == 0 or value["role"] == 2
]
server_implementations = [
    name
    for name, value in IMPLEMENTATIONS.items()
    if value["role"] == 1 or value["role"] == 2
]

replace_arg = get_args().replace
if replace_arg:
    for s in replace_arg.split(","):
        pair = s.split("=")
        if len(pair) != 2:
            sys.exit("Invalid format for replace")
        name, image = pair[0], pair[1]
        if name not in IMPLEMENTATIONS:
            sys.exit("Implementation " + name + " not found.")
        implementations[name] = image


def get_impls(arg, availableImpls, role) -> List[str]:
    if not arg:
        return availableImpls
    impls = []
    for s in arg.split(","):
        if s not in availableImpls:
            sys.exit(role + " implementation " + s + " not found.")
        impls.append(s)
    return impls


def get_tests(arg) -> List[testcases.TestCase]:
    if arg is None:
        return TESTCASES
    elif not arg:
        return []
    tests = []
    for t in arg.split(","):
        if t not in [tc.name() for tc in TESTCASES]:
            sys.exit("Test case " + t + " not found.")
        tests += [tc for tc in TESTCASES if tc.name() == t]
    return tests


def get_measurements(arg) -> List[testcases.TestCase]:
    if arg is None:
        return MEASUREMENTS
    elif not arg:
        return []
    tests = []
    for t in arg.split(","):
        if t not in [tc.name() for tc in MEASUREMENTS]:
            sys.exit("Measurement " + t + " not found.")
        tests += [tc for tc in MEASUREMENTS if tc.name() == t]
    return tests


InteropRunner(
    implementations=implementations,
    servers=get_impls(get_args().server, server_implementations, "Server"),
    clients=get_impls(get_args().client, client_implementations, "Client"),
    tests=get_tests(get_args().test),
    measurements=get_measurements(get_args().measurement),
    output=get_args().json,
).run()
