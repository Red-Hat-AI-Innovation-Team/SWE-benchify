FROM golang:1.26.0

RUN apt-get update -qq && \
    apt-get install -y --no-install-recommends git patch && \
    rm -rf /var/lib/apt/lists/*
ENV GOFLAGS="-mod=vendor"

RUN git clone https://github.com/kubernetes/kubernetes.git /testbed && \
    cd /testbed && git checkout 6f093ef29234787b51fc80154c0fa9988a1d7853 && \
    git branch -f main 6f093ef29234787b51fc80154c0fa9988a1d7853

WORKDIR /testbed
RUN make all
RUN mkdir -p /logs/verifier /logs/agent
RUN chmod -R 777 /testbed /logs
RUN git config --system --add safe.directory /testbed
