#!/usr/bin/env python3
"""Publish interop results to the caozhiyi.github.io repository.

Takes the aggregated result.json and writes it into the static site
layout expected by the interop results viewer:

    public/interop/quic/logs/quic/
        logs.json                      list of available runs (newest first)
        latest/result.json             copy of the most recent run
        logs_<runname>/result.json     per-run aggregated result

Per-test logs are intentionally NOT published: raw server/client logs
grow to hundreds of MB and exceed GitHub's repository file size limits,
and the viewer only consumes the aggregated pass/fail matrix.

Usage:
    python publish_site.py --run-name logs_2026-10-16T03:30 \
        --result result.json --site-dir website --keep-runs 30
"""
import argparse
import json
import os
import shutil


def get_args():
    parser = argparse.ArgumentParser()
    parser.add_argument("--run-name", required=True,
                        help="name of this run, e.g. logs_2026-10-16T03:30")
    parser.add_argument("--result", required=True,
                        help="path to the aggregated result.json")
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

# 2. refresh the "latest" pointer (git repos can't hold symlinks -> copy)
latest = os.path.join(data_root, "latest")
if os.path.isdir(latest):
    shutil.rmtree(latest)
shutil.copytree(run_dir, latest)

# 3. logs.json - list of available runs, newest first
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

# 4. drop runs that fell out of the keep window
for entry in os.listdir(data_root):
    if entry.startswith("logs_") and entry not in runs:
        shutil.rmtree(os.path.join(data_root, entry))

print("Published {}".format(args.run_name))
