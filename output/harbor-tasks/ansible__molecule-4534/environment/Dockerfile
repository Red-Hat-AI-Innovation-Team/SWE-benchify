FROM python:3.11-slim

RUN apt-get update -qq && \
    apt-get install -y --no-install-recommends git patch build-essential && \
    rm -rf /var/lib/apt/lists/*

RUN pip install --no-cache-dir pytest

RUN git clone https://github.com/ansible/molecule.git /testbed && \
    cd /testbed && git checkout e5e165a6c94d58433d76282dee7df25a118b922f

WORKDIR /testbed
RUN mkdir -p /logs/verifier
