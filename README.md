# Interop Test Runner

The Interop Test Runner automatically generates interoperability matrices by running test cases across different implementations. It currently supports two protocols:

* **[QUIC](quic.md)**
* **[WebTransport](webtransport.md)**

Registered implementations and their Docker images are listed in [implementations_quic.json](implementations_quic.json) and [implementations_webtransport.json](implementations_webtransport.json).

Live results are published at [interop.seemann.io](https://interop.seemann.io/).

## Publications

* Research Article: [Automating QUIC Interoperability Testing](https://dl.acm.org/doi/10.1145/3405796.3405826)
* IETF Blog Post: [Automating interoperability testing to improve open standards for the Internet](https://www.ietf.org/blog/quic-automated-interop-testing/)

## Requirements

The Interop Runner is written in Python 3. You'll need:

* Python 3 modules:

```bash
pip3 install -r requirements.txt
```

* [Docker](https://docs.docker.com/engine/install/) and [docker compose](https://docs.docker.com/compose/).
* [Wireshark](https://www.wireshark.org/download.html) (version 4.5.0 or newer).

## Running the Interop Runner

Run the QUIC interop tests:

```bash
python3 run.py
```

Run WebTransport interop tests:

```bash
python3 run.py -p webtransport
```

Use `-s` and `-c` to select specific server and client implementations, and `-t` to select specific test cases:

```bash
python3 run.py -s quic-go -c ngtcp2 -t handshake,transfer
```

## Building an Endpoint

Each implementation is packaged as a Docker image. The test runner communicates with implementations entirely through environment variables and mounted directories.

The test case is passed using the `TESTCASE` environment variable. If your implementation doesn't support a test case, it MUST exit with status code 127. This allows new test cases to be added without breaking existing implementations.

See [quic.md](quic.md) and [webtransport.md](webtransport.md) for protocol-specific setup instructions and test case definitions.

To add your implementation, create a Docker image following the instructions for [setting up an endpoint in the quic-network-simulator](https://github.com/quic-interop/quic-network-simulator), publish it on [Docker Hub](https://hub.docker.com) and add it to [implementations_quic.json](implementations_quic.json) or [implementations_webtransport.json](implementations_webtransport.json). Once your implementation is ready to interop, please send us a PR with this addition.

### Multi-Platform Builds

The [online interop runner](https://interop.seemann.io/) requires `linux/amd64` images. If you build on a different architecture (e.g. Apple silicon), use `--platform linux/amd64` with `docker build`.

The recommended approach is a multi-platform build providing both `amd64` and `arm64` images:

```bash
docker buildx create --use
docker buildx build --pull --push --platform linux/amd64,linux/arm64 -t <name:tag> .
```

## IPv6 Support

To enable IPv6 support for the simulator on Linux, the `ip6table_filter` kernel module needs to be loaded on the host:

```bash
sudo modprobe ip6table_filter
```

## Logs

The Interop Runner saves log files to the `logs` directory (overwritten on each run).

Log files are organized as `<server>_<client>/<testcase>/`. Each directory contains:
* `output.txt` — console output from the test runner (including failure reasons).
* `server/` and `client/` — server and client log files.
* `sim/` — pcaps recorded by the simulator.

Implementations that export TLS secrets should use the [NSS Key Log format](https://developer.mozilla.org/en-US/docs/Mozilla/Projects/NSS/Key_Log_Format). The `SSLKEYLOGFILE` environment variable points to a file in the logs directory.

Implementations that support [qlog](https://github.com/quiclog/internet-drafts) should export log files to the directory specified by the `QLOGDIR` environment variable.
