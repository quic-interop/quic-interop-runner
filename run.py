#!/usr/bin/env python3

import argparse
import sys
from typing import List, Tuple

import testcase
from implementations import (
    Role,
    get_quic_implementations,
    get_webtransport_implementations,
)
from interop import InteropRunner
from testcases_quic import MEASUREMENTS, TESTCASES_QUIC
from testcases_webtransport import TESTCASES_WEBTRANSPORT


def main():
    def bullet_list(testcases: List[testcase.TestCase]) -> str:
        """Format test cases as one bullet per line."""
        return "\n".join("  - " + tc.name() for tc in testcases)

    def get_args():
        test_help = "test cases (comma-separated).\n" "  QUIC:\n" + bullet_list(
            TESTCASES_QUIC
        ) + "\n  Measurements (QUIC only):\n" + bullet_list(
            MEASUREMENTS
        ) + "\n  WebTransport:\n" + bullet_list(
            TESTCASES_WEBTRANSPORT
        )

        parser = argparse.ArgumentParser(
            formatter_class=argparse.RawTextHelpFormatter,
        )
        parser.add_argument(
            "-p",
            "--protocol",
            default="quic",
            help="quic / webtransport",
        )
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
            help=test_help,
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
        return parser.parse_args()

    protocol = get_args().protocol
    if protocol == "quic":
        impls = get_quic_implementations()
    elif protocol == "webtransport":
        impls = get_webtransport_implementations()
    else:
        sys.exit("Unknown protocol: " + protocol)

    implementations_all = {
        name: {"image": value["image"], "url": value["url"]}
        for name, value in impls.items()
    }
    client_implementations = [
        name
        for name, value in impls.items()
        if value["role"] == Role.BOTH or value["role"] == Role.CLIENT
    ]
    server_implementations = [
        name
        for name, value in impls.items()
        if value["role"] == Role.BOTH or value["role"] == Role.SERVER
    ]

    replace_arg = get_args().replace
    if replace_arg:
        for s in replace_arg.split(","):
            pair = s.split("=")
            if len(pair) != 2:
                sys.exit("Invalid format for replace")
            name, image = pair[0], pair[1]
            if name not in impls:
                sys.exit("Implementation " + name + " not found.")
            implementations_all[name]["image"] = image

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
    ) -> Tuple[List[testcase.TestCase], List[testcase.TestCase]]:
        if protocol == "quic":
            testcases = TESTCASES_QUIC
            measurements = MEASUREMENTS
        elif protocol == "webtransport":
            testcases = TESTCASES_WEBTRANSPORT
            measurements = []  # no measurements in webtransport mode
        if arg is None:
            return testcases, measurements
        elif arg == "onlyTests":
            return testcases, []
        elif arg == "onlyMeasurements":
            return [], measurements
        elif not arg:
            return []
        tests = []
        chosen_measurements = []
        for t in arg.split(","):
            if t in [tc.name() for tc in testcases]:
                tests += [tc for tc in testcases if tc.name() == t]
            elif t in [tc.name() for tc in measurements]:
                chosen_measurements += [tc for tc in measurements if tc.name() == t]
            else:
                print(
                    (
                        "Test case {} not found.\n"
                        "Available testcases: {}\n"
                        "Available measurements: {}"
                    ).format(
                        t,
                        ", ".join([t.name() for t in testcases]),
                        ", ".join([t.name() for t in measurements]),
                    )
                )
                sys.exit()
        return tests, chosen_measurements

    t = get_tests_and_measurements(get_args().test)
    clients = get_impls(get_args().client, client_implementations, "Client")
    servers = get_impls(get_args().server, server_implementations, "Server")
    # If there is only one client or server, we should not automatically mark tests as unsupported
    no_auto_unsupported = set()
    for kind in [clients, servers]:
        if len(kind) == 1:
            no_auto_unsupported.add(kind[0])
    return InteropRunner(
        implementations=implementations_all,
        client_server_pairs=get_impl_pairs(clients, servers, get_args().must_include),
        tests=t[0],
        measurements=t[1],
        output=get_args().json,
        markdown=get_args().markdown,
        debug=get_args().debug,
        log_dir=get_args().log_dir,
        save_files=get_args().save_files,
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
