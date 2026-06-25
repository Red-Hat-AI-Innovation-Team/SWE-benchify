FROM golang:1.26.0

RUN apt-get update -qq && \
    apt-get install -y --no-install-recommends git patch && \
    rm -rf /var/lib/apt/lists/*
ENV GOFLAGS="-mod=vendor"

RUN git clone https://github.com/kubernetes/kubernetes.git /testbed && \
    cd /testbed && git checkout -B main 84cacae7046df93c1f6f8ea97c912d948e1ad06a

WORKDIR /testbed
RUN mkdir -p /logs/verifier /logs/agent
RUN chmod -R 777 /testbed /logs
