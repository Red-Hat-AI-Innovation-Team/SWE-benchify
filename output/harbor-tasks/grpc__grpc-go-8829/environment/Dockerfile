FROM golang:1.25

RUN apt-get update -qq && \
    apt-get install -y --no-install-recommends git patch && \
    rm -rf /var/lib/apt/lists/*

RUN git clone https://github.com/grpc/grpc-go.git /testbed && \
    cd /testbed && git checkout 6601041bab5b34e51cbb5d58666659e0b17bf6b0 && \
    git branch -f main 6601041bab5b34e51cbb5d58666659e0b17bf6b0

WORKDIR /testbed
RUN mkdir -p /logs/verifier /logs/agent
RUN chmod -R 777 /testbed /logs
