FROM python:3.11-slim

RUN apt-get update -qq && \
    apt-get install -y --no-install-recommends git patch build-essential && \
    rm -rf /var/lib/apt/lists/*

RUN pip install --no-cache-dir pytest

RUN git clone https://github.com/ansible/ansible-lint.git /testbed && \
    cd /testbed && git checkout 5781d34cc97c1e6dfa2c0a19445e010d7f1c720b

WORKDIR /testbed
RUN mkdir -p /logs/verifier
