#!/usr/bin/env python3
"""Verify that the standalone endpoint rejects wrong hostnames and CAs."""

import argparse
import os
from pathlib import Path
import socket
import subprocess
import time


def certificate(directory, name, common_name, san=None):
    cert = directory / f"{name}.pem"
    key = directory / f"{name}.key"
    command = [
        "openssl",
        "req",
        "-x509",
        "-newkey",
        "ec",
        "-pkeyopt",
        "ec_paramgen_curve:P-256",
        "-nodes",
        "-keyout",
        str(key),
        "-out",
        str(cert),
        "-days",
        "1",
        "-subj",
        f"/CN={common_name}",
    ]
    if san:
        command += ["-addext", f"subjectAltName={san}"]
    subprocess.run(
        command, check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL
    )
    return cert, key


def run_case(binary_dir, root, case):
    work = root / case
    work.mkdir()
    for directory in ("www/wt", "downloads-server", "downloads-client"):
        (work / directory).mkdir(parents=True)
    cert, key = certificate(work, "server", "localhost", "DNS:localhost")
    ca = cert
    if case == "wrong-ca":
        ca, _ = certificate(work, "unrelated-ca", "Unrelated CA")
    host = "127.0.0.1" if case == "wrong-hostname" else "localhost"
    with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as socket_fd:
        socket_fd.bind(("127.0.0.1", 0))
        port = socket_fd.getsockname()[1]
    common = {**os.environ, "TESTCASE": "handshake", "PROTOCOLS": "test"}
    server_env = {
        **common,
        "ROLE": "server",
        "XQC_WT_WWW": str(work / "www"),
        "XQC_WT_DOWNLOADS": str(work / "downloads-server"),
    }
    client_env = {
        **common,
        "ROLE": "client",
        "REQUESTS": f"https://{host}:{port}/wt",
        "XQC_WT_DOWNLOADS": str(work / "downloads-client"),
    }
    with (work / "server.stdout").open("w") as server_log:
        server = subprocess.Popen(
            [
                str(binary_dir / "wt_interop_server"),
                "-W",
                "-p",
                str(port),
                "-T",
                str(cert),
                "-K",
                str(key),
                "-L",
                str(work / "server.log"),
            ],
            env=server_env,
            cwd=work,
            stdout=server_log,
            stderr=subprocess.STDOUT,
        )
        try:
            time.sleep(0.2)
            if server.poll() is not None:
                raise AssertionError(f"server failed to start: {work}")
            client = subprocess.run(
                [
                    str(binary_dir / "wt_interop_client"),
                    "-W",
                    "-U",
                    client_env["REQUESTS"],
                    "-J",
                    str(ca),
                    "-K",
                    "5",
                    "-L",
                    str(work / "client.log"),
                ],
                env=client_env,
                cwd=work,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                timeout=10,
            )
            (work / "client.stdout").write_bytes(client.stdout)
            log = (work / "client.log").read_text()
            if client.returncode != 1 or "certificate verify failed" not in log:
                raise AssertionError(f"expected explicit TLS failure: {work}")
            if b"WT ready" in client.stdout:
                raise AssertionError("invalid certificate established a session")
            if (work / "downloads-client/negotiated_protocol.txt").exists():
                raise AssertionError("invalid certificate recorded success")
            print(f"PASS: TLS {case} rejected", flush=True)
        finally:
            server.terminate()
            try:
                server.wait(timeout=5)
            except subprocess.TimeoutExpired:
                server.kill()
                server.wait()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--bin-dir", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    args.output.mkdir(parents=True, exist_ok=False)
    for case in ("wrong-hostname", "wrong-ca"):
        run_case(args.bin_dir.resolve(), args.output.resolve(), case)


if __name__ == "__main__":
    main()
