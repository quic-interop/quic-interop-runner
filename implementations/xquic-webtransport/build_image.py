#!/usr/bin/env python3
"""Build separate XQUIC and runner-adapter checkouts with source provenance."""

import argparse
import hashlib
from pathlib import Path
import shlex
import subprocess
import shutil
import tempfile

ADAPTER = Path(__file__).resolve().parent


def source_files(root):
    names = (
        subprocess.check_output(
            ["git", "ls-files", "-z", "--cached", "--others", "--exclude-standard"],
            cwd=root,
        )
        .decode()
        .split("\0")
    )
    return [
        name
        for name in sorted(set(names))
        if name and (root / name).is_file() and not name.startswith("openspec/")
    ]


def source_digest(root, names):
    digest = hashlib.sha256()
    for name in names:
        path = root / name
        if path.suffix == ".md":
            continue
        data = path.read_bytes()
        digest.update(name.encode() + b"\0")
        digest.update(str(len(data)).encode() + b"\0" + data)
    return digest.hexdigest()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--xquic", type=Path, required=True)
    parser.add_argument("--image", default="xquic-webtransport-interop:local")
    parser.add_argument(
        "--source-url",
        default=("https://github.com/quic-interop/quic-interop-runner"),
        help="repository associated with the published container package",
    )
    parser.add_argument("--platform", default="linux/amd64")
    parser.add_argument("--target", help="optional Docker build stage")
    parser.add_argument(
        "--docker-command",
        default="docker",
        help="Docker CLI prefix, optionally including an SSH/VM wrapper",
    )
    args = parser.parse_args()
    root = args.xquic.resolve()
    files = source_files(root)
    adapter_files = sorted(
        str(p.relative_to(ADAPTER))
        for p in ADAPTER.rglob("*")
        if p.is_file()
        and "__pycache__" not in p.parts
        and "build" not in p.relative_to(ADAPTER).parts
    )
    revision = subprocess.check_output(
        ["git", "rev-parse", "HEAD"], cwd=root, text=True
    ).strip()
    docker = shlex.split(args.docker_command)
    (root / "build").mkdir(exist_ok=True)
    with tempfile.TemporaryDirectory(
        prefix="interop-context-", dir=root / "build"
    ) as temporary:
        context = Path(temporary)
        for source, names, prefix in [
            (root, files, "xquic"),
            (ADAPTER, adapter_files, "adapter"),
        ]:
            for name in names:
                destination = context / prefix / name
                destination.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(source / name, destination)
        command = docker + [
            "build",
            "-f",
            str(context / "adapter/Dockerfile"),
            "--build-arg",
            f"IMAGE_SOURCE={args.source_url}",
            "--build-arg",
            f"XQUIC_REVISION={revision}",
            "--build-arg",
            f"XQUIC_SOURCE_SHA256={source_digest(root, files)}",
            "--build-arg",
            f"ADAPTER_SOURCE_SHA256={source_digest(ADAPTER, adapter_files)}",
            "--platform",
            args.platform,
            "-t",
            args.image,
        ]
        if args.target:
            command += ["--target", args.target]
        subprocess.run(command + [str(context)], check=True)
    subprocess.run(docker + ["image", "inspect", args.image], check=True)


if __name__ == "__main__":
    main()
