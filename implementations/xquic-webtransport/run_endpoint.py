#!/usr/bin/env python3
"""QUIC Interop Runner entry point for WebTransport H and UR."""

import os
import subprocess
import sys
from urllib.parse import urlsplit


def endpoint_command(env):
    role = env.get("ROLE")
    case = env.get("TESTCASE")
    supported = {
        "client": {"handshake", "transfer-unidirectional-receive"},
        "server": {"handshake", "transfer"},
    }
    if case not in supported.get(role, set()):
        return None
    binary_dir = env.get("XQC_WT_BIN_DIR", "/usr/local/bin")
    logs = env.get("XQC_WT_LOGS", "/logs")
    certs = env.get("XQC_WT_CERTS", "/certs")
    args = [
        f"{binary_dir}/wt_interop_{role}",
        "-W",
        "-v",
        "16",
        "-l",
        "d",
        "-L",
        f"{logs}/{role}.log",
        "-k",
        env.get("SSLKEYLOGFILE", f"{logs}/keys.log"),
    ]
    if role == "server":
        args += [
            "-p",
            env.get("XQC_WT_PORT", "443"),
            "-T",
            f"{certs}/cert.pem",
            "-K",
            f"{certs}/priv.key",
        ]
    else:
        requests = env.get("REQUESTS", "").split()
        if not requests:
            raise ValueError("REQUESTS is required for the client")
        first = urlsplit(requests[0])
        if (
            first.scheme != "https"
            or not first.hostname
            or first.username
            or first.password
            or first.query
            or first.fragment
        ):
            raise ValueError("REQUESTS must contain plain HTTPS URLs")
        parts = first.path.strip("/").split("/")
        if not parts[0] or parts[0] in {".", ".."}:
            raise ValueError("REQUESTS must identify a session endpoint")
        session_url = f"https://{first.netloc}/{parts[0]}"
        args += ["-U", session_url, "-J", f"{certs}/ca.pem", "-K", "45"]
    return args


def main():
    try:
        args = endpoint_command(os.environ)
        if args is None:
            return 127
        subprocess.run(["/setup.sh"], check=True)
        if os.environ["ROLE"] == "client":
            subprocess.run(
                ["/wait-for-it.sh", "sim:57832", "-s", "-t", "30"], check=True
            )
        os.execv(args[0], args)
    except (ValueError, OSError, subprocess.CalledProcessError) as exc:
        print(f"WebTransport endpoint failed: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
