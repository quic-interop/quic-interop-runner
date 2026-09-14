FROM martenseemann/quic-network-simulator-endpoint@sha256:3b2b9e6fa317da238c8140a7b6d2bf8d4d45a8464b873eecac3ff2a32520b71a AS endpoint

FROM endpoint AS dependencies
ARG BORINGSSL_REV=27c62ff54d72b4a2dd55c3c4ace527550a051626
RUN apt-get update && DEBIAN_FRONTEND=noninteractive apt-get install -y \
    --no-install-recommends build-essential ca-certificates cmake git \
    golang-go libevent-dev libcunit1-dev ruby && \
    rm -rf /var/lib/apt/lists/*
RUN git init /deps/boringssl && \
    git -C /deps/boringssl remote add origin \
        https://github.com/google/boringssl.git && \
    git -C /deps/boringssl fetch --depth 1 origin "${BORINGSSL_REV}" && \
    git -C /deps/boringssl checkout --detach FETCH_HEAD

FROM dependencies AS builder
COPY xquic /xquic
WORKDIR /xquic
RUN XQC_SSL_PATH=/deps/boringssl XQC_BUILD_JOBS=4 \
    ./scripts/validate.sh test
COPY adapter /adapter
RUN cmake -S /adapter -B /adapter/build \
    -DXQUIC_SOURCE=/xquic -DXQUIC_BUILD=/xquic/build/validation \
    -DBORINGSSL_ROOT=/deps/boringssl -DXQUIC_COVERAGE=ON && \
    cmake --build /adapter/build -j4 && \
    ctest --test-dir /adapter/build --output-on-failure

FROM endpoint AS runtime
RUN apt-get update && DEBIAN_FRONTEND=noninteractive apt-get install -y \
    --no-install-recommends libevent-2.1-7t64 ca-certificates python3 && \
    rm -rf /var/lib/apt/lists/*
ARG XQUIC_REVISION=unknown
ARG XQUIC_SOURCE_SHA256=unknown
ARG ADAPTER_SOURCE_SHA256=unknown
ARG IMAGE_SOURCE=https://github.com/quic-interop/quic-interop-runner
LABEL org.opencontainers.image.source="${IMAGE_SOURCE}" \
    org.opencontainers.image.revision="${XQUIC_REVISION}" \
    io.xquic.source.sha256="${XQUIC_SOURCE_SHA256}" \
    io.xquic.adapter.source.sha256="${ADAPTER_SOURCE_SHA256}"
COPY --from=builder /adapter/build/wt_interop_client /usr/local/bin/
COPY --from=builder /adapter/build/wt_interop_server /usr/local/bin/
COPY adapter/run_endpoint.py /run_endpoint.py
RUN mkdir -p /logs /downloads /www
ENTRYPOINT ["python3", "/run_endpoint.py"]
