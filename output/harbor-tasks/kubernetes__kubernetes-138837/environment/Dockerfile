FROM golang:1.26.0

RUN apt-get update -qq && \
    apt-get install -y --no-install-recommends git patch && \
    rm -rf /var/lib/apt/lists/*
ENV GOFLAGS="-mod=vendor"

RUN git clone https://github.com/kubernetes/kubernetes.git /testbed && \
    cd /testbed && git checkout d7e0dc363e1f237aa78bc0fb19fe39f1fc0e00f4 && \
    git branch -f main d7e0dc363e1f237aa78bc0fb19fe39f1fc0e00f4

WORKDIR /testbed
RUN make all
RUN mkdir -p /logs/verifier /logs/agent
RUN chmod -R 777 /testbed /logs
RUN git config --system --add safe.directory /testbed
