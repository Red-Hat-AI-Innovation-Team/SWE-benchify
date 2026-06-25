FROM golang:1.25

RUN apt-get update -qq && \
    apt-get install -y --no-install-recommends git patch && \
    rm -rf /var/lib/apt/lists/*

RUN git clone https://github.com/grpc/grpc-go.git /testbed && \
    cd /testbed && git checkout -B main a481b8f755bccf5c0308f1530e785bb58a770150

WORKDIR /testbed
RUN mkdir -p /logs/verifier /logs/agent
RUN chmod -R 777 /testbed /logs
