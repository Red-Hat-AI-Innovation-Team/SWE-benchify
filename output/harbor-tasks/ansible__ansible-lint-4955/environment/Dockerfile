FROM python:3.11-slim

RUN apt-get update -qq && \
    apt-get install -y --no-install-recommends git patch build-essential && \
    rm -rf /var/lib/apt/lists/*

RUN pip install --no-cache-dir pytest

RUN git clone https://github.com/ansible/ansible-lint.git /testbed && \
    cd /testbed && git checkout -B main c3df6882119368c8161bffbac279a3a040c5aafd

WORKDIR /testbed
RUN mkdir -p /logs/verifier /logs/agent
RUN chmod -R 777 /testbed /logs
