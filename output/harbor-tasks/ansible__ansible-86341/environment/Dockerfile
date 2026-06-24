FROM python:3.11-slim

RUN apt-get update -qq && \
    apt-get install -y --no-install-recommends git patch build-essential && \
    rm -rf /var/lib/apt/lists/*

RUN pip install --no-cache-dir pytest

RUN git clone https://github.com/ansible/ansible.git /testbed && \
    cd /testbed && git checkout 2cedaa24b6b0d7cbe691f8aae0f23764ccdb38dd

WORKDIR /testbed
RUN mkdir -p /logs/verifier
