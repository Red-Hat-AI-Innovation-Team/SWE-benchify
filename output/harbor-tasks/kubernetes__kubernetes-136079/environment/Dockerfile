FROM golang:1.26.0

RUN apt-get update -qq && \
    apt-get install -y --no-install-recommends git patch && \
    rm -rf /var/lib/apt/lists/*
ENV GOFLAGS="-mod=vendor"

RUN git clone https://github.com/kubernetes/kubernetes.git /testbed && \
    cd /testbed && git checkout -B main 51579e9c36436fd2d35ffccc441de1dbebdceaca

WORKDIR /testbed
RUN mkdir -p /logs/verifier /logs/agent
RUN chmod -R 777 /testbed /logs
