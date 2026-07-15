FROM golang:latest

LABEL org.opencontainers.image.source=https://github.com/Red-Hat-AI-Innovation-Team/SWE-benchify

RUN apt-get update -qq && apt-get install -y --no-install-recommends git curl ca-certificates && rm -rf /var/lib/apt/lists/*

# Clone repo at base commit
RUN (git clone https://github.com/containers/podman.git /testbed && \
    cd /testbed && (git checkout e239f32ad720cb591d2548c50d1a20f70d9c1e81 || \
    (git fetch origin e239f32ad720cb591d2548c50d1a20f70d9c1e81 && \
     git checkout e239f32ad720cb591d2548c50d1a20f70d9c1e81))) || \
    (rm -rf /testbed && mkdir -p /testbed && cd /testbed && git init && \
     curl -sL https://github.com/containers/podman/archive/e239f32ad720cb591d2548c50d1a20f70d9c1e81.tar.gz | \
     tar xz --strip-components=1 && git add -A && git commit -q -m base)

WORKDIR /testbed

RUN cd /testbed && go mod download

# Ensure /logs structure exists for Harbor verifier
RUN mkdir -p /logs/verifier /logs/agent /logs/artifacts
