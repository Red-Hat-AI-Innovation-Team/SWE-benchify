FROM golang:1.25

RUN apt-get update -qq && \
    apt-get install -y --no-install-recommends git patch && \
    rm -rf /var/lib/apt/lists/*

RUN git clone https://github.com/grpc/grpc-go.git /testbed && \
    cd /testbed && git checkout -B main 39f16539d2463c05d52b4c44137831fd5f73f7d9

WORKDIR /testbed
RUN mkdir -p /logs/verifier /logs/agent
RUN chmod -R 777 /testbed /logs
