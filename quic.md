# QUIC

The Interop Runner mounts `/www` into your server Docker container, containing one or more randomly generated files. Your server is expected to run on port 443 and serve files from this directory.

The Interop Runner mounts `/downloads` into your client Docker container (initially empty). Your client is expected to store downloaded files into this directory. The URLs of the files to download are passed using the `REQUESTS` environment variable (space-separated).

After the transfer is completed, the client container is expected to exit with status 0 (or status 1 on error). The Interop Runner verifies that the client downloaded the expected files with matching contents. For certain test cases, the Interop Runner also inspects the pcap to verify protocol-level requirements.

The Interop Runner generates a key and certificate chain, mounted into `/certs`. The server loads its private key from `priv.key` and the certificate chain from `cert.pem`.

### Examples

If you're not familiar with Docker, these implementations may be helpful references:

* quic-go: [Dockerfile](https://github.com/quic-go/quic-go/blob/master/interop/Dockerfile), [run_endpoint.sh](https://github.com/quic-go/quic-go/blob/master/interop/run_endpoint.sh) and [CI config](https://github.com/quic-go/quic-go/blob/master/.github/workflows/build-interop-docker.yml)
* quicly: [Dockerfile](https://github.com/h2o/quicly/blob/master/misc/quic-interop-runner/Dockerfile) and [run_endpoint.sh](https://github.com/h2o/quicly/blob/master/misc/quic-interop-runner/run_endpoint.sh)
* quiche: [Dockerfile](https://github.com/cloudflare/quiche/blob/master/Dockerfile) and [run_endpoint.sh](https://github.com/cloudflare/quiche/blob/master/tools/qns/run_endpoint.sh)
* neqo: [Dockerfile](https://github.com/mozilla/neqo/blob/main/qns/Dockerfile) and [interop.sh](https://github.com/mozilla/neqo/blob/main/qns/interop.sh)
* msquic: [Dockerfile](https://github.com/microsoft/msquic/blob/master/Dockerfile), [run_endpoint.sh](https://github.com/microsoft/msquic/blob/master/scripts/run_endpoint.sh) and [CI config](https://github.com/microsoft/msquic/blob/master/.azure/azure-pipelines.docker.yml)

Feel free to add links to your implementation here!

## Test Cases

Unless noted otherwise, test cases use HTTP/0.9 for file transfers. The name in parentheses is the value of the `TESTCASE` environment variable passed into your Docker container.

* **Version Negotiation** (`versionnegotiation`): Tests that a server sends a Version Negotiation packet in response to an unknown QUIC version number. The client should start a connection using an unsupported version number (it can use a reserved version number to do so), and should abort the connection attempt when receiving the Version Negotiation packet. Currently disabled due to [#20](https://github.com/quic-interop/quic-interop-runner/issues/20).

* **Handshake** (`handshake`): Tests the successful completion of the handshake. The client is expected to establish a single QUIC connection to the server and download one or multiple small files. Servers should not send a Retry packet in this test case.

* **Transfer** (`transfer`): Tests both flow control and stream multiplexing. The client should use small initial flow control windows for both stream- and connection-level flow control, such that during the transfer of files on the order of 1 MB the flow control window needs to be increased. The client is expected to establish a single QUIC connection, and use multiple streams to concurrently download the files.

* **ChaCha20** (`chacha20`): Client and server are expected to offer **only** ChaCha20 as a ciphersuite. The client then downloads the files.

* **KeyUpdate** (`keyupdate`, client only): The client is expected to make sure that a key update happens early in the connection (during the first MB transferred). It doesn't matter which peer actually initiated the update.

* **Retry** (`retry`): Tests that the server can generate a Retry, and that the client can act upon it (i.e. use the Token provided in the Retry packet in the Initial packet).

* **Resumption** (`resumption`): Tests QUIC session resumption (without 0-RTT). The client establishes a connection and downloads the first file. The server provides a session ticket. After downloading the first file, the client closes the connection, resumes using the session ticket, and downloads the remaining file(s).

* **0-RTT** (`zerortt`): Tests QUIC 0-RTT. The client establishes a connection and downloads the first file. The server provides a session ticket that allows 0-RTT on the next attempt. After downloading the first file, the client closes the connection, establishes a 0-RTT connection, and requests the remaining file(s).

* **HTTP/3** (`http3`): Tests a simple HTTP/3 connection. The client downloads multiple files using HTTP/3, requesting and transferring them in parallel.

* **Handshake Loss** (`multiconnect`): Tests resilience of the handshake to high loss. The client establishes multiple connections (sequential or in parallel) and uses each connection to download a single file.

* **V2** (`v2`): The client starts connecting in QUIC v1 with a `version_information` transport parameter that includes QUIC v2 (`0x6b3343cf`) in `other_versions`. The server selects QUIC v2 via compatible version negotiation. The client downloads one small file in QUIC v2.

* **Port Rebinding** (`rebind-port`): A NAT is simulated that changes the client's source port after the handshake. The server should perform path validation.

* **Address Rebinding** (`rebind-addr`): A NAT is simulated that changes the client's IP address after the handshake. The server should perform path validation.

* **Connection Migration** (`connectionmigration`): The server provides its preferred addresses to the client during the handshake. The client performs active migration to one of those addresses.
