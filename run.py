#!/usr/bin/env python3

import argparse
import sys
from typing import List, Tuple

import testcases
from implementations import IMPLEMENTATIONS, Role
from interop import InteropRunner
from testcases import MEASUREMENTS, TESTCASES

implementations = {
    name: {"image": value["image"], "url": value["url"]}
    for name, value in IMPLEMENTATIONS.items()
}
client_implementations = [
    name
    for name, value in IMPLEMENTATIONS.items()
    if value["role"] == Role.BOTH or value["role"] == Role.CLIENT
]
server_implementations = [
    name
    for name, value in IMPLEMENTATIONS.items()
    if value["role"] == Role.BOTH or value["role"] == Role.SERVER
]


def main():
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
        parser.add_argument(
            "-t",
            "--test",
            help="test cases (comma-separatated). Valid test cases are: "
            + ", ".join([x.name() for x in TESTCASES + MEASUREMENTS]),
        )
        parser.add_argument(
            "-r",
            "--replace",
            help="replace path of implementation. Example: -r myquicimpl=dockertagname",
        )
        parser.add_argument(
            "-l",
            "--log-dir",
            help="log directory",
            default="",
        )
        parser.add_argument(
            "-f", "--save-files", help="save downloaded files if a test fails"
        )
        parser.add_argument(
            "-j", "--json", help="output the matrix to file in json format"
        )
        return parser.parse_args()

    replace_arg = get_args().replace
    if replace_arg:
        for s in replace_arg.split(","):
            pair = s.split("=")
            if len(pair) != 2:
                sys.exit("Invalid format for replace")
            name, image = pair[0], pair[1]
            if name not in IMPLEMENTATIONS:
                sys.exit("Implementation " + name + " not found.")
            implementations[name]["image"] = image

    def get_impls(arg, availableImpls, role) -> List[str]:
        if not arg:
            return availableImpls
        impls = []
        for s in arg.split(","):
            if s not in availableImpls:
                sys.exit(role + " implementation " + s + " not found.")
            impls.append(s)
        return impls

    def get_tests_and_measurements(
        arg,
    ) -> Tuple[List[testcases.TestCase], List[testcases.TestCase]]:
        if arg is None:
            return TESTCASES, MEASUREMENTS
        elif arg == "onlyTests":
            return TESTCASES, []
        elif arg == "onlyMeasurements":
            return [], MEASUREMENTS
        elif not arg:
            return []
        tests = []
        measurements = []
        for t in arg.split(","):
            if t in [tc.name() for tc in TESTCASES]:
                tests += [tc for tc in TESTCASES if tc.name() == t]
            elif t in [tc.name() for tc in MEASUREMENTS]:
                measurements += [tc for tc in MEASUREMENTS if tc.name() == t]
            else:
                print(
                    (
                        "Test case {} not found.\n"
                        "Available testcases: {}\n"
                        "Available measurements: {}"
                    ).format(
                        t,
                        ", ".join([t.name() for t in TESTCASES]),
                        ", ".join([t.name() for t in MEASUREMENTS]),
                    )
                )
                sys.exit()
        return tests, measurements

    t = get_tests_and_measurements(get_args().test)
    return InteropRunner(
        implementations=implementations,
        servers=get_impls(get_args().server, server_implementations, "Server"),
        clients=get_impls(get_args().client, client_implementations, "Client"),
        tests=t[0],
        measurements=t[1],
        output=get_args().json,
        debug=get_args().debug,
        log_dir=get_args().log_dir,
        save_files=get_args().save_files,
    ).run()


if __name__ == "__main__":
    sys.exit(main())
