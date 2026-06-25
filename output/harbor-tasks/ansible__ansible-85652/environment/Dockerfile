FROM python:3.11-slim

RUN apt-get update -qq && \
    apt-get install -y --no-install-recommends git patch build-essential && \
    rm -rf /var/lib/apt/lists/*

RUN pip install --no-cache-dir pytest

RUN git clone https://github.com/ansible/ansible.git /testbed && \
    cd /testbed && git checkout -B main 76748b8478abc10b7bb476db86a27d3041d47d40

WORKDIR /testbed
RUN mkdir -p /logs/verifier /logs/agent
RUN chmod -R 777 /testbed /logs
