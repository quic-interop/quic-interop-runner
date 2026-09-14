# XQUIC WebTransport endpoint

This image runs XQUIC's `wt_interop_client` and `wt_interop_server`, built by
its existing demo CMake configuration. Application behavior lives in
`demo/xqc_webtrans_interop.c` in [XQUIC](https://github.com/alibaba/xquic).
The container entrypoint only maps the runner environment to demo arguments.

The [application contract](../../webtransport.md) defines fixtures and paths.
Supported client cases are `handshake` (H) and
`transfer-unidirectional-receive` (UR); the server supports `handshake` and
the unidirectional response part of `transfer`. Other client cases return 127.
The client verifies `/certs/ca.pem` and the requested hostname.

## Build and test

From the runner checkout, use a clean XQUIC checkout providing the interop
demo and its native cases:

```sh
python3 implementations/xquic-webtransport/test_endpoint.py
docker buildx build --load --platform linux/amd64 \
    --build-context xquic=/path/to/xquic \
    --tag xquic-webtransport-interop:local \
    implementations/xquic-webtransport
```

The Docker builder runs XQUIC's complete unit suite and six native endpoint
cases: H, protocol rejection, UR, missing file, wrong CA and wrong hostname.
These cases use the same build directory as the binaries copied to the final
image. Native tests and their assertions are maintained in XQUIC.

Use the official runner to test the image:

```sh
python3 run.py -p webtransport -s xquic -c xquic \
    -t handshake,transfer-unidirectional-receive \
    -r xquic=xquic-webtransport-interop:local
```

## Publication

The [fork workflow](../../.github/workflows/xquic-webtransport-image.yml)
publishes `ghcr.io/yanmei-liu/xquic-webtransport-interop` from
`Yanmei-Liu/quic-interop-runner`. It verifies that the upstream and fork XQUIC
feature branches match the pinned full revision, checks out that revision,
and builds and tests before pushing `sha-<runner-commit>` and `latest`.
Image labels identify the XQUIC and runner revisions; the workflow summary
records the pushed digest. The package must remain publicly pullable by the
scheduled runner. Use the digest to reproduce a published image.
