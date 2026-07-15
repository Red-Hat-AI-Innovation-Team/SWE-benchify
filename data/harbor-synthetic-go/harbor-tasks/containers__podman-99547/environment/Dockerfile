FROM golang:latest

LABEL org.opencontainers.image.source=https://github.com/Red-Hat-AI-Innovation-Team/SWE-benchify

RUN apt-get update -qq && apt-get install -y --no-install-recommends git curl ca-certificates && rm -rf /var/lib/apt/lists/*

# Clone repo at base commit
RUN (git clone https://github.com/containers/podman.git /testbed && \
    cd /testbed && (git checkout eca7d85562ce93cdd191f50d12d3bf982ba7fba1 || \
    (git fetch origin eca7d85562ce93cdd191f50d12d3bf982ba7fba1 && \
     git checkout eca7d85562ce93cdd191f50d12d3bf982ba7fba1))) || \
    (rm -rf /testbed && mkdir -p /testbed && cd /testbed && git init && \
     curl -sL https://github.com/containers/podman/archive/eca7d85562ce93cdd191f50d12d3bf982ba7fba1.tar.gz | \
     tar xz --strip-components=1 && git add -A && git commit -q -m base)

WORKDIR /testbed

RUN cd /testbed && go mod download

# Ensure /logs structure exists for Harbor verifier
RUN mkdir -p /logs/verifier /logs/agent /logs/artifacts
