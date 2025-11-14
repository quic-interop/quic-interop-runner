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
        parser.add_argument(
            "-m",
            "--markdown",
            help="output the matrix in Markdown format",
            action="store_const",
            const=True,
            default=False,
        )
        parser.add_argument(
            "-i",
            "--must-include",
            help="implementation that must be included",
        )
        parser.add_argument(
            "-n",
            "--no-auto-unsupported",
            help="implementations for which auto-marking as unsupported when all tests fail should be skipped",
        )
        parser.add_argument(
            "--parallel",
            type=int,
            default=None,
            help="Number of tests to run in parallel. Use -1 for all CPU cores, "
            "or specify a number. Default: half of available cores",
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

    def get_impl_pairs(clients, servers, must_include) -> List[Tuple[str, str]]:
        impls = []
        for client in clients:
            for server in servers:
                if (
                    must_include is None
                    or client == must_include
                    or server == must_include
                ):
                    impls.append((client, server))
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
    clients = get_impls(get_args().client, client_implementations, "Client")
    servers = get_impls(get_args().server, server_implementations, "Server")
    # If there is only one client or server, we should not automatically mark tests as unsupported
    no_auto_unsupported = set()
    for kind in [clients, servers]:
        if len(kind) == 1:
            no_auto_unsupported.add(kind[0])
    return InteropRunner(
        implementations=implementations,
        client_server_pairs=get_impl_pairs(clients, servers, get_args().must_include),
        tests=t[0],
        measurements=t[1],
        output=get_args().json,
        markdown=get_args().markdown,
        debug=get_args().debug,
        log_dir=get_args().log_dir,
        save_files=get_args().save_files,
        parallel=get_args().parallel,
        no_auto_unsupported=(
            no_auto_unsupported
            if get_args().no_auto_unsupported is None
            else get_impls(
                get_args().no_auto_unsupported, clients + servers, "Client/Server"
            )
        ),
    ).run()


if __name__ == "__main__":
    sys.exit(main())
