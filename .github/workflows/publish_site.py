#!/usr/bin/env python3
"""Publish interop results to the caozhiyi.github.io repository.

Takes the aggregated result.json plus the per-combination log artifacts
(downloaded from the workflow run) and copies them into the static site
layout expected by the interop results viewer:

    public/interop/quic/logs/quic/
        logs.json                      list of available runs (newest first)
        latest/result.json             copy of the most recent run
        logs_<runname>/result.json     per-run aggregated result
        logs_<runname>/<server>_<client>/<test>/...   per-test logs

Since GitHub Pages has no directory listing, an index.html is generated
for every directory so the viewer's log links resolve to a browsable page.

Usage:
    python publish_site.py --run-name logs_2026-10-16T03:30 \
        --result result.json --logs-glob "logs-*" --site-dir website --keep-runs 30
"""
import argparse
import glob
import html
import json
import os
import shutil
import sys


def get_args():
    parser = argparse.ArgumentParser()
    parser.add_argument("--run-name", required=True,
                        help="name of this run, e.g. logs_2026-10-16T03:30")
    parser.add_argument("--result", required=True,
                        help="path to the aggregated result.json")
    parser.add_argument("--logs-glob", default="logs-*",
                        help="glob matching the downloaded logs artifacts")
    parser.add_argument("--site-dir", required=True,
                        help="path to the caozhiyi.github.io checkout")
    parser.add_argument("--keep-runs", type=int, default=30,
                        help="number of runs to keep on the site")
    return parser.parse_args()


args = get_args()

data_root = os.path.join(args.site_dir, "public/interop/quic/logs/quic")
run_dir = os.path.join(data_root, args.run_name)
os.makedirs(run_dir, exist_ok=True)

# 1. aggregated result
shutil.copy(args.result, os.path.join(run_dir, "result.json"))

# 2. per-combination logs
# Each downloaded artifact directory (logs-*) contains the contents of the
# job's logs/ directory, i.e. one <server>_<client> folder per combination.
for artifact in glob.glob(args.logs_glob):
    if not os.path.isdir(artifact):
        continue
    for combo in os.listdir(artifact):
        src = os.path.join(artifact, combo)
        if not os.path.isdir(src):
            continue
        dst = os.path.join(run_dir, combo)
        if os.path.isdir(dst):
            shutil.rmtree(dst)
        shutil.copytree(src, dst)

# 3. refresh the "latest" pointer (git repos can't hold symlinks -> copy)
latest = os.path.join(data_root, "latest")
if os.path.isdir(latest):
    shutil.rmtree(latest)
shutil.copytree(run_dir, latest)

# 4. logs.json - list of available runs, newest first
logs_json_path = os.path.join(data_root, "logs.json")
runs = []
if os.path.exists(logs_json_path):
    try:
        with open(logs_json_path) as f:
            runs = json.load(f)
    except (IOError, json.JSONDecodeError):
        runs = []
if args.run_name in runs:
    runs.remove(args.run_name)
runs = [args.run_name] + runs
runs = runs[: args.keep_runs]
with open(logs_json_path, "w") as f:
    json.dump(runs, f)

# 5. drop runs that fell out of the keep window
for entry in os.listdir(data_root):
    if entry.startswith("logs_") and entry not in runs:
        shutil.rmtree(os.path.join(data_root, entry))

# 6. generate directory indexes (GitHub Pages has no auto directory listing)
INDEX_TEMPLATE = """<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<title>quicx interop logs: {rel}</title>
<style>
body {{ font-family: sans-serif; margin: 2rem; }}
a {{ display: block; padding: 0.15rem 0; color: #0066cc; text-decoration: none; }}
a:hover {{ text-decoration: underline; }}
h1 {{ font-size: 1.2rem; }}
</style>
</head>
<body>
<h1>Index of {rel}</h1>
{links}
</body>
</html>
"""


def make_index(dirpath):
    rel = os.path.relpath(dirpath, data_root)
    links = []
    if rel != ".":
        links.append('<a href="../index.html">../</a>')
    for entry in sorted(os.listdir(dirpath)):
        if entry == "index.html":
            continue
        full = os.path.join(dirpath, entry)
        if os.path.isdir(full):
            links.append('<a href="{}">{}/</a>'.format(entry, html.escape(entry)))
        else:
            size = os.path.getsize(full)
            links.append('<a href="{}">{} ({:.1f} KB)</a>'.format(
                entry, html.escape(entry), size / 1024.0))
    with open(os.path.join(dirpath, "index.html"), "w") as f:
        f.write(INDEX_TEMPLATE.format(rel=html.escape(rel),
                                      links="\n".join(links)))


for dirpath, dirnames, _ in os.walk(data_root):
    make_index(dirpath)

print("Published {} ({} combinations)".format(args.run_name,
      len(os.listdir(run_dir))))
