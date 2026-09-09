# syntax=docker/dockerfile:1.7

# Keep the toolchain tag explicit so a rebuild does not silently change the
# relay binary's build environment.
FROM rust:1.85.1-bookworm AS builder

WORKDIR /src
COPY remote/relay/Cargo.toml remote/relay/Cargo.lock remote/relay/
COPY remote/relay/src remote/relay/src
RUN cargo build --manifest-path remote/relay/Cargo.toml --release --locked

FROM debian:12.11-slim

RUN apt-get update \
    && apt-get install --no-install-recommends --yes ca-certificates curl \
    && rm -rf /var/lib/apt/lists/* \
    && groupadd --system --gid 10001 lamtools \
    && useradd --system --uid 10001 --gid lamtools --home-dir /nonexistent --shell /usr/sbin/nologin lamtools \
    && install --directory --owner=lamtools --group=lamtools /data

COPY --from=builder /src/remote/relay/target/release/lamtools-relay /usr/local/bin/lamtools-relay

WORKDIR /data
ENV DATABASE_PATH=/data/lamtools.db \
    LAMTOOLS_RELAY_BIND=0.0.0.0:8787 \
    REGISTRATION_MODE=closed \
    RUST_LOG=info

USER 10001:10001
VOLUME ["/data"]
EXPOSE 8787
STOPSIGNAL SIGTERM
HEALTHCHECK --interval=30s --timeout=5s --start-period=15s --retries=3 \
    CMD curl --fail --silent http://127.0.0.1:8787/healthz || exit 1

LABEL org.opencontainers.image.title="LamTools Relay" \
      org.opencontainers.image.version="0.1.0" \
      org.opencontainers.image.description="Authenticated opaque Noise tunnel relay for LamTools"

ENTRYPOINT ["/usr/local/bin/lamtools-relay"]
