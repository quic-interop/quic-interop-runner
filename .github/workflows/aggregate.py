import argparse
import json
import sys


def get_args():
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "-s", "--server", help="server implementations (comma-separated)"
    )
    parser.add_argument(
        "-c", "--client", help="client implementations (comma-separated)"
    )
    parser.add_argument("-l", "--log-dir", help="log directory")
    parser.add_argument("-o", "--output", help="output file (stdout if not set)")
    return parser.parse_args()


servers = get_args().server.split(",")
clients = get_args().client.split(",")
result = {
    "servers": servers,
    "clients": clients,
    "log_dir": get_args().log_dir,
    "results": [],
    "measurements": [],
}


def parse(server: str, client: str, cat: str):
    filename = server + "_" + client + "_" + cat + ".json"
    try:
        with open(filename) as f:
            data = json.load(f)
    except IOError:
        print("Warning: Couldn't open file " + filename)
        result[cat].append([])
        return
    parse_data(server, client, cat, data)


def parse_data(server: str, client: str, cat: str, data: object):
    if len(data["servers"]) != 1:
        sys.exit("expected exactly one server")
    if data["servers"][0] != server:
        sys.exit("inconsistent server")
    if len(data["clients"]) != 1:
        sys.exit("expected exactly one client")
    if data["servers"][0] != server:
        sys.exit("inconsistent client")
    if "start_time" not in result or data["start_time"] < result["start_time"]:
        result["start_time"] = data["start_time"]
    if "end_time" not in result or data["end_time"] > result["end_time"]:
        result["end_time"] = data["end_time"]
    result[cat].append(data[cat][0])


for client in clients:
    for server in servers:
        parse(server, client, "results")
        parse(server, client, "measurements")

if get_args().output:
    f = open(get_args().output, "w")
    json.dump(result, f)
    f.close()
else:
    print(json.dumps(result))
