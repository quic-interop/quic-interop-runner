#!/usr/bin/env python3
"""Exercise native H/UR endpoints and explicit protocol rejection over UDP."""

import argparse
import hashlib
import os
from pathlib import Path
import socket
import subprocess
import time

from run_endpoint import endpoint_command


def run_case(binary_dir, root, case, client_protocols, server_protocols):
    case_root = root / case
    case_root.mkdir()
    for directory in [
        "certs",
        "server-www/wt",
        "client-www",
        "client-downloads",
        "server-downloads",
        "client-logs",
        "server-logs",
    ]:
        (case_root / directory).mkdir(parents=True, exist_ok=True)
    certs = case_root / "certs"
    subprocess.run(
        [
            "openssl",
            "req",
            "-x509",
            "-newkey",
            "ec",
            "-pkeyopt",
            "ec_paramgen_curve:P-256",
            "-nodes",
            "-keyout",
            str(certs / "priv.key"),
            "-out",
            str(certs / "cert.pem"),
            "-days",
            "1",
            "-subj",
            "/CN=localhost",
            "-addext",
            "subjectAltName=DNS:localhost",
        ],
        check=True,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    (certs / "ca.pem").write_bytes((certs / "cert.pem").read_bytes())
    with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as sock:
        sock.bind(("127.0.0.1", 0))
        port = sock.getsockname()[1]
    files = []
    if case == "ur":
        for index, size in enumerate(
            [100 * 1024, 500 * 1024, 250 * 1024, 1024 * 1024, 2 * 1024 * 1024]
        ):
            name = f"file-{index}.bin"
            (case_root / "server-www/wt" / name).write_bytes(os.urandom(size))
            files.append(name)
    requests = " ".join(f"https://localhost:{port}/wt/{name}" for name in files)
    if not requests:
        requests = f"https://localhost:{port}/wt"
    base = {
        **os.environ,
        "XQC_WT_BIN_DIR": str(binary_dir),
        "XQC_WT_CERTS": str(certs),
        "XQC_WT_PORT": str(port),
    }
    server_env = {
        **base,
        "ROLE": "server",
        "TESTCASE": "transfer" if files else "handshake",
        "PROTOCOLS": server_protocols,
        "REQUESTS": "",
        "XQC_WT_WWW": str(case_root / "server-www"),
        "XQC_WT_DOWNLOADS": str(case_root / "server-downloads"),
        "XQC_WT_LOGS": str(case_root / "server-logs"),
    }
    client_env = {
        **base,
        "ROLE": "client",
        "TESTCASE": "transfer-unidirectional-receive" if files else "handshake",
        "PROTOCOLS": client_protocols,
        "REQUESTS": requests,
        "XQC_WT_WWW": str(case_root / "client-www"),
        "XQC_WT_DOWNLOADS": str(case_root / "client-downloads"),
        "XQC_WT_LOGS": str(case_root / "client-logs"),
    }
    with (case_root / "server.stdout").open("w") as server_log:
        server = subprocess.Popen(
            endpoint_command(server_env),
            cwd=case_root,
            env=server_env,
            stdout=server_log,
            stderr=subprocess.STDOUT,
        )
        try:
            time.sleep(0.3)
            if server.poll() is not None:
                raise RuntimeError(f"server failed to start: {case_root}")
            with (case_root / "client.stdout").open("w") as client_log:
                client = subprocess.run(
                    endpoint_command(client_env),
                    cwd=case_root,
                    env=client_env,
                    stdout=client_log,
                    stderr=subprocess.STDOUT,
                    timeout=50,
                )
            text = (case_root / "client.stdout").read_text()
            if case == "reject":
                if client.returncode == 0 or "status=403" not in text:
                    raise AssertionError(
                        f"expected explicit 403 rejection: {case_root}"
                    )
                if (case_root / "client-downloads/negotiated_protocol.txt").exists():
                    raise AssertionError("rejected negotiation recorded as successful")
            else:
                if client.returncode != 0:
                    raise AssertionError(f"client failed: {case_root}")
                selected = next(
                    p for p in client_protocols.split() if p in server_protocols.split()
                )
                for role in (("client", "server") if case == "handshake" else ()):
                    actual = (
                        (case_root / f"{role}-downloads/negotiated_protocol.txt")
                        .read_text()
                        .strip()
                    )
                    if actual != selected:
                        raise AssertionError(
                            f"{role} selected {actual!r}, expected {selected!r}"
                        )
                for name in files:
                    source = (case_root / "server-www/wt" / name).read_bytes()
                    downloaded = (case_root / "client-downloads/wt" / name).read_bytes()
                    if source != downloaded:
                        raise AssertionError(f"file mismatch: {name}")
                    print(
                        f"{name}: {len(source)} bytes sha256={hashlib.sha256(source).hexdigest()}"
                    )
            print(f"PASS: {case}", flush=True)
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
    for case, client, server in [
        ("handshake", "client-only first second", "second first server-only"),
        ("ur", "files", "files"),
        ("reject", "client-only", "server-only"),
    ]:
        run_case(args.bin_dir.resolve(), args.output.resolve(), case, client, server)


if __name__ == "__main__":
    main()
