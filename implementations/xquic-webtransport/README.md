# XQUIC WebTransport endpoint

This adapter implements **H** (`handshake`) and **UR**
(`transfer-unidirectional-receive`) using the XQUIC WebTransport library.
The runner's [application protocol](../../webtransport.md) and
[test definitions](../../testcases_webtransport.py) define the fixtures and
pass criteria. The endpoint application, container packaging and local runner
helpers live here; WebTransport protocol implementation and unit tests remain
in [XQUIC](https://github.com/alibaba/xquic).

## Contract

| Role | TESTCASE | Behavior |
|---|---|---|
| Client/server | `handshake` | Select the first client-preferred common protocol; both endpoints write `/downloads/negotiated_protocol.txt`. |
| Client | `transfer-unidirectional-receive` | Send concurrent `GET <filename>` requests on separate unidirectional streams; receive and save each `PUSH` stream through FIN. |
| Server | `transfer` | Serve the UR subset: open a fresh unidirectional stream for each `GET`, sending `PUSH <filename>\n`, file content and FIN. |

The shared server-side `transfer` selector implements only its unidirectional
response path. Other client testcases return 127. Upload, bidirectional and
datagram transfer, and multiple sessions are not implemented by this adapter.

`ROLE`, `TESTCASE`, `PROTOCOLS` and `REQUESTS` follow the runner contract.
Fixtures live under `/www/<session>/`, downloads under `/downloads/<session>/`,
and certificates under `/certs/`. The client verifies `/certs/ca.pem` and the
URL hostname. `SSLKEYLOGFILE` controls the TLS secret log.

Application buffers retain short writes and fragmented headers through FIN.
A session retains at most 64 stream states, including closed streams, until
session teardown; attempts to exceed that bound fail explicitly.
File access is relative to the session directory and rejects traversal,
symlink components, duplicate downloads and non-regular files. Protocol
negotiation is delegated to XQUIC's application-protocol API on the client;
the server application selects from the offered Structured Field list.

## Build from two local checkouts

The XQUIC checkout must provide `xqc_wt_client_open_session_with_protocols`
and `xqc_wt_session_get_application_protocol`. Build the local source into an
amd64 endpoint image from this runner checkout:

```sh
python3 implementations/xquic-webtransport/build_image.py \
    --xquic /path/to/xquic --image xquic-webtransport-interop:local
```

The helper creates an isolated source context from tracked and unignored
files, excluding XQUIC build artifacts and temporary plans. It copies XQUIC
and this adapter separately, pins BoringSSL, builds XQUIC through its
validation entry point, then builds and tests the adapter with CMake.
Image labels record the XQUIC commit and independent source digests for both
repositories. Local uncommitted code is included in those digests.
`--source-url` selects the repository associated with the container package;
local builds default to the upstream runner repository.

Docker Compose and the public runner require Linux networking. On macOS, run
Docker in a dedicated Linux VM. An optional `--docker-command` prefix supports
a VM/SSH wrapper when the source-context path is shared at the same absolute
location. The default platform is `linux/amd64`.

## Run the official cases locally

Install the runner requirements, Docker Compose and the required tshark
version. Pull the selected official images listed in
[implementations_webtransport.json](../../implementations_webtransport.json)
and `martenseemann/quic-network-simulator` before running:

```sh
python3 implementations/xquic-webtransport/run_matrix.py \
    --runner /path/to/clean/quic-interop-runner \
    --output /path/to/new-results \
    --image xquic-webtransport-interop:local
```

Defaults are XQUIC's self-pair, webtransport-go, flupke, ngtcp2 and Firefox.
Use `--peers ''` for the self-pair or a comma-separated subset. Chrome is
available upstream but excluded from this helper's default selection.
Browser implementations have only a client role.

The helper requires a clean runner checkout, copies its tracked files and
adds only a local XQUIC registration. Images are pinned to their inspected
local IDs for the run. Peer code, official test logic and exported case JSON
remain unchanged. Failures are never automatically relabeled unsupported.
The helper returns zero only when every requested H/UR case succeeds and
every runner process exits zero. Failed, unsupported or missing cases and
runner errors produce a nonzero exit status.

Each direction and case runs in a separate official `run.py` process: the
defaults execute eight pairs and sixteen cases. After every process, the
helper removes only containers whose inspected Compose working-directory
label exactly matches this run's generated `runner/` directory. This also
cleans up after an upstream timeout or nonzero exit. If cleanup fails,
remaining cases stay unrun. The helper never removes other containers by
name or prunes Docker resources. Run one matrix at a time because the
upstream Compose file uses fixed container names.

`--case-timeout` bounds a whole upstream invocation (300 seconds by default),
including its child processes. This outer limit does not change the official
test's timeout or success criteria.

The new output directory preserves each official JSON unchanged at
`upstream/<server>_<client>/<case>.json`, with its console output in the
adjacent `.log` file. `results.md` links to these originals and summarizes the
combined `results.json`. `provenance.json` records image identities, commands,
exit status and cleanup outcomes. Each invocation receives a unique log root
under `logs/<server>_<client>/<case>/`; the official runner creates its normal
endpoint-log and PCAP hierarchy beneath it. H checks exactly
one handshake and both negotiated-protocol files. UR checks one handshake and
five files byte for byte: 100 KiB, 500 KiB, 250 KiB, 1 MiB and 2 MiB.

The top-level registry uses
`ghcr.io/yanmei-liu/xquic-webtransport-interop:latest`. Local runs override that
entry with `--image`. The published package must be public before the
scheduled runner can pull it anonymously.

## Publish from the runner fork

The [image workflow](../../.github/workflows/xquic-webtransport-image.yml)
runs only in `Yanmei-Liu/quic-interop-runner`. It keeps all adapter and image
automation in this repository. Both `alibaba/xquic` and `Yanmei-Liu/xquic`
must expose `feat/webtrans-interop` at the same commit; no publishing workflow
is added to either XQUIC source branch.

Before publishing, replace the workflow's `XQUIC_REVISION` with the full,
tested XQUIC commit SHA and synchronize the two source branches. The workflow
compares both remote branch heads with that SHA before checking out the fork
at the pinned revision. An unset pin, missing branch or differing head stops
the build. Push adapter or workflow changes to
`codex/xquic-webtransport-interop` or `master` in the runner fork to trigger it.
GitHub supports [push-triggered workflows on feature branches](
https://docs.github.com/en/actions/reference/workflows-and-actions/events-that-trigger-workflows#push).
An existing run can be retried with:

```sh
gh run list --repo Yanmei-Liu/quic-interop-runner \
    --workflow xquic-webtransport-image.yml
gh run rerun RUN_ID --repo Yanmei-Liu/quic-interop-runner
```

The workflow builds and tests `linux/amd64`, then uses its `GITHUB_TOKEN`
with `packages: write` to publish `latest` and `sha-<runner-commit>` tags.
The runner commit fixes both the adapter and its XQUIC revision. The source
label connects the package to `Yanmei-Liu/quic-interop-runner`; the revision
label identifies the XQUIC commit. The run summary records both commits and
the pushed digest. Use that digest when reproducing a published run.
This follows GitHub's [Container registry authentication and repository
linking](https://docs.github.com/en/packages/working-with-a-github-packages-registry/working-with-the-container-registry).

New packages default to private, including packages published from public
repositories. After the first successful upload, open the package in
[Yanmei-Liu's Packages](https://github.com/Yanmei-Liu?tab=packages), choose
**Package settings**, then **Change visibility**, select **Public**, and
confirm the package name. This setting cannot later be changed back to
private. The supported visibility configuration is documented in GitHub's
[package access and visibility guide](
https://docs.github.com/en/packages/learn-github-packages/configuring-a-packages-access-control-and-visibility#configuring-visibility-of-packages-for-your-personal-account).
The [REST package API](https://docs.github.com/en/rest/packages/packages)
does not provide a visibility-update endpoint.

Verify anonymous access before submitting the registry entry for use by the
public runner. On a Linux Docker host, use an empty Docker configuration:

```sh
anonymous_config="$(mktemp -d)"
docker --config "$anonymous_config" pull \
    ghcr.io/yanmei-liu/xquic-webtransport-interop:latest
rmdir "$anonymous_config"
```

## Native regression

Build the XQUIC library using its own `scripts/validate.sh test` first, then
build this adapter against that separate checkout:

```sh
cmake -S implementations/xquic-webtransport -B build/xquic-webtransport \
    -DXQUIC_SOURCE=/path/to/xquic \
    -DXQUIC_BUILD=/path/to/xquic/build/validation \
    -DBORINGSSL_ROOT=/path/to/boringssl -DXQUIC_COVERAGE=ON
cmake --build build/xquic-webtransport -j4
ctest --test-dir build/xquic-webtransport --output-on-failure
python3 implementations/xquic-webtransport/test_runner.py
python3 implementations/xquic-webtransport/test_build_image.py
python3 implementations/xquic-webtransport/test_loopback.py \
    --bin-dir build/xquic-webtransport --output /path/to/new-loopback-results
python3 implementations/xquic-webtransport/test_runtime_tls.py \
    --bin-dir build/xquic-webtransport --output /path/to/new-tls-results
```

The loopback checks prove client-order protocol negotiation, all five binary
file downloads and an explicit HTTP 403 response for disjoint protocols.
`XQC_WT_BIN_DIR`, `XQC_WT_CERTS`, `XQC_WT_LOGS`, `XQC_WT_PORT`, `XQC_WT_WWW`
and `XQC_WT_DOWNLOADS` override container paths for native tests. The TLS checks reject an unrelated CA and a hostname mismatch. Generated
certificates, secret logs and run results must remain outside source control.
