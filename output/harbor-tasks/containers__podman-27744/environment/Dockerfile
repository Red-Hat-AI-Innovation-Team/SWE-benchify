FROM golang:1.25.6

RUN apt-get update -qq && \
    apt-get install -y --no-install-recommends git patch gawk libassuan-dev libbtrfs-dev libgpgme-dev libseccomp-dev libsystemd-dev libclone-perl man-db pandoc python3-pip && \
    rm -rf /var/lib/apt/lists/*
ENV GOFLAGS="-mod=vendor"

RUN git clone https://github.com/containers/podman.git /testbed && \
    cd /testbed && git checkout -B main a51012b99e64f4f5a4efd4e438b7485f156cfffe

WORKDIR /testbed
RUN mkdir -p /logs/verifier /logs/agent
RUN chmod -R 777 /testbed /logs
