# Protocol

The protocol used to test WebTransport builds on top of HTTP/0.9, but extends it with the PUSH method. This allows us to test both server-initiated streams as well as datagrams. Requests can be initiated in both directions: the client can request files from the server, or the server can request files from the client once a session is established.

Implementations MUST read the `PROTOCOLS` environment (a space-separated list of strings) variable and use these for application protocol negotiation.

## Running a Server

The server MAY determine expected WebTransport endpoints by scanning the `/www/` directory for top-level subdirectories at startup. Each such subdirectory name (e.g., webtransport1 in `/www/webtransport1/`) corresponds to an endpoint path (e.g., `/webtransport1`), including empty subdirectories for session-only tests like handshake. When a session is established on a path with a matching subdirectory, the server MUST serve requested files from the corresponding subpaths within `/www/`. Alternatively, implementations MAY accept sessions on any path without scanning or restricting, serving files relative to the session path if a matching structure exists in `/www/`.

No test requires the establishment of multiple QUIC connections. All WebTransport sessions are multiplexed on a single QUIC connection. A server therefore SHOULD only accept a single QUIC connection.

## Requesting Files

The client might be passed a list of files to request over one or more WebTransport sessions using the `REQUESTS` environment variable (a space-separated list of paths). The first component of the path identifies the WebTransport endpoint, the remainder the path to the file. For example:
* https://server/webtransport1/file1.txt
* https://server/webtransport1/file2.txt
* https://server/webtransport2/file3.txt

The client is expected to establish the first WebTransport session on `/webtransport1` and download `file1.txt` and `file2.txt`, and the second WebTransport session on `/webtransport2` and download `file3.txt`. Both sessions MUST be established in parallel, on the same underlying QUIC connection.

If the client is passed a path that doesn't contain a file (e.g. https://server/webtransport/), it MUST establish a WebTransport session with this endpoint, but not request any files.

The server might also be passed a list of files to request using the `REQUESTS` environment variable. These paths don't contain a host, but only a path. The first component of the path identifies the WebTransport endpoint that the client used to establish the connection, the remainder the path to the file. For example:
* `webtransport1/file1.txt`
* `webtransport1/file2.txt`
* `webtransport2/file3.txt`

The server is expected to wait for the client to establish a WebTransport session on the given endpoints, and then requests the files from the client.

The files to serve are mounted into the container at `/www/`, in a directory structure that matches the paths passed to the client. For example, if the client is passed the path https://server/webtransport123/file1.txt, the server will serve the file from `/www/webtransport123/file1.txt`.

Files MUST be saved into the `/downloads/` directory, in a directory structure that matches the paths passed to the client. For example, if the client is passed the path https://server/webtransport123/file1.txt, the server will save the file to `/downloads/webtransport123/file1.txt`.

## Using Unidirectional Streams

If instructed to transfer a file using a unidirectional stream, the client MUST open a new unidirectional stream, and send `GET <filename>` and then close the stream. For example, if the client is passed the path https://server/webtransport123/file1.txt, the client will send `GET file1.txt` on the session established to the https://server/webtransport123 endpoint. It is expected that all requests are sent in parallel.

The sender MUST then open a new unidirectional stream, send `PUSH <filename>\n`, followed by the file contents, and then close the stream. It is expected that all pushes are sent in parallel.


## Using Bidirectional Streams

If instructed to transfer a file using a bidirectional stream, the client MUST open a new bidirectional stream, and send `GET <filename>` and then close the stream. For example, if the client is passed the path https://server/webtransport123/file1.txt, the client will send `GET file1.txt` on the session established to the https://server/webtransport123 endpoint. It is expected that all requests are sent in parallel.

The sender MUST then send the file contents on the same stream, and then close the stream. It is expected that all responses are sent in parallel.

## Using Datagrams

If instructed to transfer a file using a datagram, the client MUST send `GET <filename>` as a datagram. For example, if the client is passed the path https://server/webtransport123/file1.txt, the client will send `GET file1.txt` as a datagram on the session established to the https://server/webtransport123 endpoint.

The sender MUST then send the `PUSH <filename>\n` followed by the file contents as a datagram. The file is guaranteed to be small enough to fit into a single (sub-MTU-sized) datagram.


## Testcases

**Handshake** (`handshake`): Tests the successful completion of the handshake. Both client and server save the negotiated protocol in a file called `negotiated_protocol.txt` in the directory specified by the `DOWNLOAD_DIR` environment variable.

**Transfer** (`transfer`): In this test, the WebTransport endpoint should respond to requests on unidirectional and on bidirectional streams, as well as requests sent in datagrams. It doesn't issue any requests itself.

**Transfer Unidirectional** (`transfer-unidirectional-send`): Tests the successful transfer of a file using a unidirectional stream. The client is expected to send the request and the file contents in parallel. The server is expected to receive the request and the file contents in parallel.

**Transfer Bidirectional** (`transfer-bidirectional-send`): Tests the successful transfer of a file using a bidirectional stream. The client is expected to send the request and the file contents in parallel. The server is expected to receive the request and the file contents in parallel.

**Transfer Datagram** (`transfer-datagram-send`): Tests the successful transfer of a file using a datagram. The client is expected to send the request and the file contents in parallel. The server is expected to receive the request and the file contents in parallel.
