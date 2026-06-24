FROM golang:1.26.0

RUN apt-get update -qq && \
    apt-get install -y --no-install-recommends git patch && \
    rm -rf /var/lib/apt/lists/*
ENV GOFLAGS="-mod=vendor"

RUN git clone https://github.com/kubernetes/kubernetes.git /testbed && \
    cd /testbed && git checkout c6886b7d697a41f0b779abfaf5aeba66b4c577d1

WORKDIR /testbed
RUN mkdir -p /logs/verifier
