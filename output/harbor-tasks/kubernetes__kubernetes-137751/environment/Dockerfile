FROM golang:1.26.0

RUN apt-get update -qq && \
    apt-get install -y --no-install-recommends git patch && \
    rm -rf /var/lib/apt/lists/*
ENV GOFLAGS="-mod=vendor"

RUN git clone https://github.com/kubernetes/kubernetes.git /testbed && \
    cd /testbed && git checkout eb0da686b86f3e1a8c7519a37a6bde64daf09867 && \
    git branch -f main eb0da686b86f3e1a8c7519a37a6bde64daf09867

WORKDIR /testbed
RUN make all
RUN mkdir -p /logs/verifier /logs/agent
RUN chmod -R 777 /testbed /logs
RUN git config --system --add safe.directory /testbed
