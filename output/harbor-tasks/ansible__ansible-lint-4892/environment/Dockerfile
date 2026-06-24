FROM python:3.11-slim

RUN apt-get update -qq && \
    apt-get install -y --no-install-recommends git patch build-essential && \
    rm -rf /var/lib/apt/lists/*

RUN pip install --no-cache-dir pytest

RUN git clone https://github.com/ansible/ansible-lint.git /testbed && \
    cd /testbed && git checkout 6b2cee92ad42e71ffcdeeceac03a5cc484b807a9

WORKDIR /testbed
RUN mkdir -p /logs/verifier
