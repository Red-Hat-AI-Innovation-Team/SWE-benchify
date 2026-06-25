FROM golang:1.26.3

RUN apt-get update -qq && \
    apt-get install -y --no-install-recommends git patch make gcc openssh-server openssh-client nginx unzip zip fcgiwrap wget sudo tini ca-certificates gpg gpg-agent tzdata connect-proxy shellcheck && \
    rm -rf /var/lib/apt/lists/*

RUN git clone https://github.com/argoproj/argo-cd.git /testbed && \
    cd /testbed && git checkout 8b1415a6b7f27f41b3b6a1cf9fe20f75b3cfd022 && \
    git branch -f main 8b1415a6b7f27f41b3b6a1cf9fe20f75b3cfd022

WORKDIR /testbed
RUN mkdir -p /logs/verifier /logs/agent
RUN chmod -R 777 /testbed /logs
