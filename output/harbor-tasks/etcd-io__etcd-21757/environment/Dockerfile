FROM golang:1.26

RUN apt-get update -qq && \
    apt-get install -y --no-install-recommends git patch && \
    rm -rf /var/lib/apt/lists/*

RUN git clone https://github.com/etcd-io/etcd.git /testbed && \
    cd /testbed && git checkout -b main 315e04328c6a19c107081870e5cdadaa6044d45d

WORKDIR /testbed
RUN mkdir -p /logs/verifier /logs/agent
RUN chmod -R 777 /testbed /logs
