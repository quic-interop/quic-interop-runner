#!/usr/bin/env python3

import argparse
import json
import logging
import os
import os.path
import shutil
import sys
from datetime import datetime

from interop import InteropRunner
from run import client_implementations, implementations, server_implementations
from testcases import MEASUREMENTS, TESTCASES


def get_args():
    parser = argparse.ArgumentParser()
    parser.add_argument("-n", "--numlogs", help="keep this many logs")
    return parser.parse_args()


# set the CRON environment variable, so implmenetations can adjust their logging
os.environ["CRON"] = "true"

try:
    numlogs = int(get_args().numlogs)
except Exception as e:
    logging.info(e)
    sys.exit("Invalid -n argument.")

log_dir = "logs_{:%Y-%m-%dT%H:%M:%S}UTC".format(datetime.utcnow())

InteropRunner(
    implementations=implementations,
    servers=server_implementations,
    clients=client_implementations,
    tests=TESTCASES,
    measurements=MEASUREMENTS,
    output=log_dir + "/result.json",
    debug=False,
    log_dir=log_dir,
).run()

web_dir = "web/"  # directory of the index.html of the interop runner website
logs_file = web_dir + "logs.json"
try:
    with open(logs_file, "r") as f:
        lines = json.load(f)
except FileNotFoundError:
    lines = []

# make sure that web/ doesn't contain more than x old runs
while len(lines) >= numlogs:
    d = web_dir + lines[0]
    logging.info("Deleting %s.", d)
    shutil.rmtree(d)
    lines = lines[1:]

with open(logs_file, "w") as f:
    lines.append(log_dir)
    json.dump(lines, f)

# move log dir to the web folder
shutil.move(log_dir, web_dir + "/")
# adjust web/latest to point to the latest run
latest_symlink = web_dir + "latest"
try:
    os.remove(latest_symlink)
except FileNotFoundError:
    pass
os.symlink(src=log_dir, dst=latest_symlink, target_is_directory=True)
