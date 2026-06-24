FROM golang:1.25

RUN apt-get update -qq && \
    apt-get install -y --no-install-recommends git patch && \
    rm -rf /var/lib/apt/lists/*

RUN git clone https://github.com/grpc/grpc-go.git /testbed && \
    cd /testbed && git checkout adc97de9521a9f377dab5e911039842dc4de23e5

WORKDIR /testbed
RUN mkdir -p /logs/verifier
