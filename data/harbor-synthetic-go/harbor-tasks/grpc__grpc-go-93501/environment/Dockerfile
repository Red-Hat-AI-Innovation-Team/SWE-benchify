FROM golang:latest

LABEL org.opencontainers.image.source=https://github.com/Red-Hat-AI-Innovation-Team/SWE-benchify

RUN apt-get update -qq && apt-get install -y --no-install-recommends git curl ca-certificates && rm -rf /var/lib/apt/lists/*

# Clone repo at base commit
RUN (git clone https://github.com/grpc/grpc-go.git /testbed && \
    cd /testbed && (git checkout 1b37d1214eac44c0b14e63c885452cdf644cfb04 || \
    (git fetch origin 1b37d1214eac44c0b14e63c885452cdf644cfb04 && \
     git checkout 1b37d1214eac44c0b14e63c885452cdf644cfb04))) || \
    (rm -rf /testbed && mkdir -p /testbed && cd /testbed && git init && \
     curl -sL https://github.com/grpc/grpc-go/archive/1b37d1214eac44c0b14e63c885452cdf644cfb04.tar.gz | \
     tar xz --strip-components=1 && git add -A && git commit -q -m base)

WORKDIR /testbed

RUN cd /testbed && go mod download

# Ensure /logs structure exists for Harbor verifier
RUN mkdir -p /logs/verifier /logs/agent /logs/artifacts
