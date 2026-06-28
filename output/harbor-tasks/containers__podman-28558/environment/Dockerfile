FROM golang:1.25.6

RUN apt-get update -qq && \
    apt-get install -y --no-install-recommends git patch gawk libassuan-dev libbtrfs-dev libgpgme-dev libseccomp-dev libsystemd-dev libclone-perl man-db pandoc python3-pip && \
    rm -rf /var/lib/apt/lists/*
ENV GOFLAGS="-mod=vendor"

RUN git clone https://github.com/containers/podman.git /testbed && \
    cd /testbed && git checkout 9ac300c6af5192c4ecd9cc1fcb2399f321575858 && \
    git branch -f main 9ac300c6af5192c4ecd9cc1fcb2399f321575858

WORKDIR /testbed
RUN make podman
RUN mkdir -p /logs/verifier /logs/agent
RUN chmod -R 777 /testbed /logs
RUN git config --system --add safe.directory /testbed
