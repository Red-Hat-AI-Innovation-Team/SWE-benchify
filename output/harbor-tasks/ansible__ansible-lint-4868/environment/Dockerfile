FROM python:3.11-slim

RUN apt-get update -qq && \
    apt-get install -y --no-install-recommends git patch build-essential && \
    rm -rf /var/lib/apt/lists/*

RUN pip install --no-cache-dir pytest

RUN git clone https://github.com/ansible/ansible-lint.git /testbed && \
    cd /testbed && git checkout 40f24c2d511c6662ba96b53a35f386cf8b0c11ad

WORKDIR /testbed
RUN mkdir -p /logs/verifier
