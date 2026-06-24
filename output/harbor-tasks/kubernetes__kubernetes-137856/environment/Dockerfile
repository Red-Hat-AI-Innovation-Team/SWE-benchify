FROM golang:1.26.0

RUN apt-get update -qq && \
    apt-get install -y --no-install-recommends git patch && \
    rm -rf /var/lib/apt/lists/*
ENV GOFLAGS="-mod=vendor"

RUN git clone https://github.com/kubernetes/kubernetes.git /testbed && \
    cd /testbed && git checkout 0eb3ae1640e0fc9db151e5063815187afeb9b5af

WORKDIR /testbed
RUN mkdir -p /logs/verifier
