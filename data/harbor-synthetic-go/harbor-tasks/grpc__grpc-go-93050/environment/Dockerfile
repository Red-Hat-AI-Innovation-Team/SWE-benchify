FROM golang:latest

LABEL org.opencontainers.image.source=https://github.com/Red-Hat-AI-Innovation-Team/SWE-benchify

RUN apt-get update -qq && apt-get install -y --no-install-recommends git curl ca-certificates && rm -rf /var/lib/apt/lists/*

# Clone repo at base commit
RUN (git clone https://github.com/grpc/grpc-go.git /testbed && \
    cd /testbed && (git checkout 4f890c3971bbb01c4a12d84b40b26c7136660c31 || \
    (git fetch origin 4f890c3971bbb01c4a12d84b40b26c7136660c31 && \
     git checkout 4f890c3971bbb01c4a12d84b40b26c7136660c31))) || \
    (rm -rf /testbed && mkdir -p /testbed && cd /testbed && git init && \
     curl -sL https://github.com/grpc/grpc-go/archive/4f890c3971bbb01c4a12d84b40b26c7136660c31.tar.gz | \
     tar xz --strip-components=1 && git add -A && git commit -q -m base)

WORKDIR /testbed

RUN cd /testbed && go mod download

# Ensure /logs structure exists for Harbor verifier
RUN mkdir -p /logs/verifier /logs/agent /logs/artifacts
