FROM golang:1.26.0

RUN apt-get update -qq && \
    apt-get install -y --no-install-recommends git patch && \
    rm -rf /var/lib/apt/lists/*
ENV GOFLAGS="-mod=vendor"

RUN git clone https://github.com/kubernetes/kubernetes.git /testbed && \
    cd /testbed && git checkout -B main a51c7d6f315a95761a1a163db7919027227e8e1f

WORKDIR /testbed
RUN mkdir -p /logs/verifier /logs/agent
RUN chmod -R 777 /testbed /logs
