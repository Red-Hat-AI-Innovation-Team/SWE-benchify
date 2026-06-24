FROM python:3.11-slim

RUN apt-get update -qq && \
    apt-get install -y --no-install-recommends git patch build-essential && \
    rm -rf /var/lib/apt/lists/*

RUN pip install --no-cache-dir pytest

RUN git clone https://github.com/ansible/ansible.git /testbed && \
    cd /testbed && git checkout b1fc98c8ad9d56ee65cc43fb46de87f2ee52b18c

WORKDIR /testbed
RUN mkdir -p /logs/verifier
