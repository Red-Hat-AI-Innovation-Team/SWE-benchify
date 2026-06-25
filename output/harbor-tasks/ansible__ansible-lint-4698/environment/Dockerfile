FROM python:3.11-slim

RUN apt-get update -qq && \
    apt-get install -y --no-install-recommends git patch build-essential && \
    rm -rf /var/lib/apt/lists/*

RUN pip install --no-cache-dir pytest

RUN git clone https://github.com/ansible/ansible-lint.git /testbed && \
    cd /testbed && git checkout -B main f16e1ce1a2ab8f94f03121ea4e499ba042677d2a

WORKDIR /testbed
RUN mkdir -p /logs/verifier /logs/agent
RUN chmod -R 777 /testbed /logs
