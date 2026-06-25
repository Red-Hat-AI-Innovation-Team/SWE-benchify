FROM python:3.11-slim

RUN apt-get update -qq && \
    apt-get install -y --no-install-recommends git patch build-essential && \
    rm -rf /var/lib/apt/lists/*

RUN pip install --no-cache-dir pytest

RUN git clone https://github.com/ansible/ansible-lint.git /testbed && \
    cd /testbed && git checkout -B main 444be15e3b7a37b66957cd9687cada9772552300

WORKDIR /testbed
RUN mkdir -p /logs/verifier /logs/agent
RUN chmod -R 777 /testbed /logs
