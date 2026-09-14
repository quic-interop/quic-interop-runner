FROM martenseemann/quic-network-simulator-endpoint@sha256:3b2b9e6fa317da238c8140a7b6d2bf8d4d45a8464b873eecac3ff2a32520b71a AS endpoint

FROM endpoint AS dependencies
ARG BORINGSSL_REV=27c62ff54d72b4a2dd55c3c4ace527550a051626
RUN apt-get update && DEBIAN_FRONTEND=noninteractive apt-get install -y \
    --no-install-recommends build-essential ca-certificates cmake git \
    golang-go libevent-dev libcunit1-dev python3 ruby && \
    rm -rf /var/lib/apt/lists/*
RUN git init /deps/boringssl && \
    git -C /deps/boringssl remote add origin \
        https://github.com/google/boringssl.git && \
    git -C /deps/boringssl fetch --depth 1 origin "${BORINGSSL_REV}" && \
    git -C /deps/boringssl checkout --detach FETCH_HEAD

FROM dependencies AS builder
COPY --from=xquic / /xquic
WORKDIR /xquic
RUN XQC_SSL_PATH=/deps/boringssl XQC_BUILD_JOBS=4 \
    ./scripts/validate.sh test && \
    XQC_BUILD_DIR=/xquic/build/validation bash scripts/case_test.sh --execute \
        --case wt_interop_handshake \
        --case wt_interop_protocol_rejected \
        --case wt_interop_ur \
        --case wt_interop_missing_file \
        --case wt_interop_wrong_ca \
        --case wt_interop_wrong_hostname

FROM endpoint AS runtime
RUN apt-get update && DEBIAN_FRONTEND=noninteractive apt-get install -y \
    --no-install-recommends libevent-2.1-7t64 ca-certificates python3 && \
    rm -rf /var/lib/apt/lists/*
ARG XQUIC_REVISION=unknown
ARG RUNNER_REVISION=unknown
ARG IMAGE_SOURCE=https://github.com/quic-interop/quic-interop-runner
LABEL org.opencontainers.image.source="${IMAGE_SOURCE}" \
    org.opencontainers.image.revision="${XQUIC_REVISION}" \
    io.xquic.runner.revision="${RUNNER_REVISION}"
COPY --from=builder /xquic/build/validation/demo/wt_interop_client /usr/local/bin/
COPY --from=builder /xquic/build/validation/demo/wt_interop_server /usr/local/bin/
COPY run_endpoint.py /run_endpoint.py
RUN mkdir -p /logs /downloads /www
ENTRYPOINT ["python3", "/run_endpoint.py"]
