#!/usr/bin/env python3
"""Run the upstream WebTransport H/UR matrix without changing peer code."""

import argparse
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import shutil
import signal
import subprocess
import sys

DEFAULT_PEERS = "webtransport-go,flupke-webtransport,ngtcp2,firefox"
CASES = (("H", "handshake"), ("UR", "transfer-unidirectional-receive"))
OWNER_LABEL = "com.docker.compose.project.working_dir"
RESULT_NAMES = {
    "succeeded": "PASS",
    "failed": "FAIL",
    "unsupported": "UNSUPPORTED",
    None: "NOT RUN",
}


def git_head(path):
    return subprocess.check_output(
        ["git", "-C", str(path), "rev-parse", "HEAD"], text=True
    ).strip()


def write_report(result, output, metadata):
    evidence = "Combined table: [results.json](results.json). "
    evidence += (
        "Image identities: [provenance.json](provenance.json). "
        "Per-case endpoint logs and PCAPs: [logs](logs/)."
    )
    lines = [
        "# WebTransport Docker interoperability",
        "",
        f"UTC: {metadata['started_at']}",
        "",
        f"Runner revision: `{metadata['runner_revision']}`",
        "",
        "H: handshake and application protocol negotiation. "
        "UR: five concurrent server-to-client unidirectional file transfers.",
        "",
        "| Client | Server | H | UR |",
        "|---|---|---|---|",
    ]
    source_rows = []
    index = 0
    for client in result["clients"]:
        for server in result["servers"]:
            records = result["results"][index]
            index += 1
            if "xquic" not in (client, server):
                continue
            cells = {
                r["abbr"]: RESULT_NAMES.get(r["result"], str(r["result"]))
                for r in records
            }
            lines.append(
                f"| {client} | {server} | {cells.get('H', 'NOT RUN')} "
                f"| {cells.get('UR', 'NOT RUN')} |"
            )
            links = []
            for abbr, case in CASES:
                path = Path("upstream") / f"{server}_{client}" / f"{case}.json"
                links.append(
                    f"[{abbr}]({path.as_posix()})"
                    if (output / path).is_file()
                    else "NOT WRITTEN"
                )
            source_rows.append(f"| {client} | {server} | {' | '.join(links)} |")
    lines += [
        "",
        "The upstream runner checks exactly one TLS handshake for each "
        "case. H checks both negotiated_protocol.txt files; UR compares "
        "all five downloaded files byte for byte (100 KiB, 500 KiB, "
        "250 KiB, 1 MiB, and 2 MiB).",
        "",
        evidence,
        "",
        "Original, unmodified JSON from each official case invocation:",
        "",
        "| Client | Server | H JSON | UR JSON |",
        "|---|---|---|---|",
        *source_rows,
        "",
        "Browser implementations are clients only. Other WebTransport "
        "testcases are outside this run. This is a local Docker run, "
        "not a published interop.seemann.io result.",
    ]
    (output / "results.md").write_text("\n".join(lines) + "\n")


def merge_results(runs, clients, servers):
    pairs = {}
    for result in runs:
        index = 0
        for client in result["clients"]:
            for server in result["servers"]:
                records = pairs.setdefault((client, server), {})
                for record in result["results"][index]:
                    abbr = record["abbr"]
                    if record["result"] is not None or abbr not in records:
                        records[abbr] = record
                index += 1
    combined = {"clients": clients, "servers": servers, "results": []}
    for client in clients:
        for server in servers:
            combined["results"].append(
                [
                    pairs.get((client, server), {}).get(
                        abbr, {"abbr": abbr, "name": case, "result": None}
                    )
                    for abbr, case in CASES
                ]
            )
    return combined


def cleanup_containers(local_runner):
    """Remove only container IDs whose inspected label proves our ownership."""
    owner = str(local_runner)
    candidates = subprocess.check_output(
        ["docker", "ps", "-aq", "--filter", f"label={OWNER_LABEL}={owner}"],
        text=True,
        timeout=30,
    ).split()
    removed = []
    if candidates:
        containers = json.loads(
            subprocess.check_output(
                ["docker", "container", "inspect", *candidates], text=True, timeout=30
            )
        )
        owned = [
            container["Id"]
            for container in containers
            if ((container.get("Config") or {}).get("Labels") or {}).get(OWNER_LABEL)
            == owner
        ]
        if owned:
            subprocess.run(
                ["docker", "container", "rm", "-f", *owned],
                check=True,
                capture_output=True,
                text=True,
                timeout=30,
            )
            removed.extend(owned)
    remaining = subprocess.check_output(
        ["docker", "ps", "-aq", "--filter", f"label={OWNER_LABEL}={owner}"],
        text=True,
        timeout=30,
    ).split()
    if remaining:
        raise RuntimeError(f"Owned containers remain after cleanup: {remaining}")
    return removed


def run_case(command, local_runner, console, timeout):
    """Bound the whole upstream process and its child processes."""
    with console.open("w") as log:
        process = subprocess.Popen(
            command,
            cwd=local_runner,
            stdout=log,
            stderr=subprocess.STDOUT,
            start_new_session=True,
        )
        timed_out = False
        try:
            try:
                status = process.wait(timeout=timeout)
            except subprocess.TimeoutExpired:
                timed_out = True
                status = 124
                log.write(f"\nWrapper timeout after {timeout}s\n")
        finally:
            # subprocess.run(shell=True) upstream can leave compose descendants.
            try:
                os.killpg(process.pid, signal.SIGKILL)
            except ProcessLookupError:
                pass
            process.wait()
    return status, timed_out


def matrix_exit_status(result):
    requested = False
    index = 0
    for client in result["clients"]:
        for server in result["servers"]:
            records = result["results"][index]
            index += 1
            if "xquic" not in (client, server):
                continue
            requested = True
            outcomes = {r["abbr"]: r["result"] for r in records}
            if any(outcomes.get(abbr) != "succeeded" for abbr in ("H", "UR")):
                return 1
    return 0 if requested else 1


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--runner",
        type=Path,
        required=True,
        help="upstream quic-interop-runner Git checkout",
    )
    parser.add_argument(
        "--output",
        type=Path,
        required=True,
        help="new evidence directory; never overwritten",
    )
    parser.add_argument("--image", default="xquic-webtransport-interop:local")
    parser.add_argument(
        "--case-timeout",
        type=int,
        default=300,
        help="whole upstream invocation timeout in seconds",
    )
    parser.add_argument(
        "--peers",
        default=DEFAULT_PEERS,
        help="comma-separated peers; empty means self-pair only",
    )
    args = parser.parse_args()
    if args.case_timeout <= 0:
        parser.error("case-timeout must be positive")
    runner = args.runner.resolve()
    output = args.output.resolve()
    if output.exists():
        parser.error("output already exists; select a new evidence directory")
    if subprocess.check_output(["git", "-C", str(runner), "diff", "HEAD", "--"]):
        parser.error("runner must have no tracked modifications")
    registry = json.loads((runner / "implementations_webtransport.json").read_text())
    peers = list(dict.fromkeys(p for p in args.peers.split(",") if p and p != "xquic"))
    unknown = set(peers) - registry.keys()
    if unknown:
        parser.error(f"unknown peers: {sorted(unknown)}")
    registry["xquic"] = {
        "image": args.image,
        "url": "https://github.com/alibaba/xquic",
        "role": "both",
    }
    clients = ["xquic"] + [p for p in peers if registry[p]["role"] != "server"]
    servers = ["xquic"] + [p for p in peers if registry[p]["role"] != "client"]
    metadata = {
        "started_at": datetime.now(timezone.utc).isoformat(),
        "runner_revision": git_head(runner),
        "images": {},
    }
    for name in ["xquic"] + peers:
        metadata["images"][name] = json.loads(
            subprocess.check_output(
                ["docker", "image", "inspect", registry[name]["image"]], text=True
            )
        )[0]
        registry[name]["image"] = metadata["images"][name]["Id"]
    metadata["images"]["sim"] = json.loads(
        subprocess.check_output(
            ["docker", "image", "inspect", "martenseemann/quic-network-simulator"],
            text=True,
        )
    )[0]
    output.mkdir(parents=True)
    local_runner = output / "runner"
    # Copy only tracked upstream files. Registration is the only customization.
    tracked = subprocess.check_output(["git", "-C", str(runner), "ls-files", "-z"])
    for name in tracked.decode().split("\0"):
        if not name:
            continue
        source = runner / name
        destination = local_runner / name
        if source.is_file():
            destination.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(source, destination)
    (local_runner / "implementations_webtransport.json").write_text(
        json.dumps(registry, indent=2) + "\n"
    )
    metadata["commands"] = []
    metadata["invocations"] = []
    status = 0
    runs = []
    pairs = [(client, "xquic") for client in clients]
    pairs += [("xquic", server) for server in servers if server != "xquic"]
    invocations = [
        (client, server, case) for client, server in pairs for _, case in CASES
    ]
    for client, server, case in invocations:
        name = f"{server}_{client}"
        result_file = output / "upstream" / name / f"{case}.json"
        result_file.parent.mkdir(parents=True, exist_ok=True)
        console = result_file.with_suffix(".log")
        command = [
            sys.executable,
            "run.py",
            "-p",
            "webtransport",
            "-s",
            server,
            "-c",
            client,
            "-t",
            case,
            "-n",
            ",".join(dict.fromkeys((server, client))),
            "-m",
            "-f",
            "true",
            "-j",
            str(result_file),
            "-l",
            str(output / "logs" / name / case),
        ]
        metadata["commands"].append(command)
        invocation = {
            "client": client,
            "server": server,
            "case": case,
            "result": str(result_file.relative_to(output)),
            "console": str(console.relative_to(output)),
            "logs": str(Path("logs") / name / case),
        }
        metadata["invocations"].append(invocation)
        (output / "provenance.json").write_text(json.dumps(metadata, indent=2) + "\n")
        print(f"Running {client} -> {server}: {case} ({console})", flush=True)
        cleanup_ok = False
        try:
            child_status, timed_out = run_case(
                command, local_runner, console, args.case_timeout
            )
            invocation.update(returncode=child_status, timed_out=timed_out)
            status = max(status, int(child_status != 0))
        except OSError as error:
            invocation["error"] = str(error)
            status = 1
        finally:
            try:
                invocation["removed_containers"] = cleanup_containers(local_runner)
                cleanup_ok = True
            except (
                OSError,
                ValueError,
                RuntimeError,
                subprocess.SubprocessError,
            ) as error:
                invocation["cleanup_error"] = str(error)
                status = 1
            (output / "provenance.json").write_text(
                json.dumps(metadata, indent=2) + "\n"
            )
        if result_file.exists():
            try:
                runs.append(json.loads(result_file.read_text()))
            except (ValueError, OSError) as error:
                invocation["result_error"] = str(error)
                status = 1
        else:
            status = 1
        if not cleanup_ok:
            print("Cleanup failed; remaining cases were not run.", flush=True)
            break
    (output / "provenance.json").write_text(json.dumps(metadata, indent=2) + "\n")
    combined = merge_results(runs, clients, servers)
    (output / "results.json").write_text(json.dumps(combined, indent=2) + "\n")
    write_report(combined, output, metadata)
    return max(status, matrix_exit_status(combined))


if __name__ == "__main__":
    sys.exit(main())
