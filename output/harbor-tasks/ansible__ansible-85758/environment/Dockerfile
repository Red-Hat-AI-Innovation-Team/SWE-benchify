FROM python:3.11-slim

RUN apt-get update -qq && \
    apt-get install -y --no-install-recommends git patch build-essential && \
    rm -rf /var/lib/apt/lists/*

RUN pip install --no-cache-dir pytest

RUN git clone https://github.com/ansible/ansible.git /testbed && \
    cd /testbed && git checkout 52b7d4d092359e776da0b79db9752bfc6ca91969 && \
    git branch -f main 52b7d4d092359e776da0b79db9752bfc6ca91969

WORKDIR /testbed
RUN pip install -e . 2>/dev/null || pip install . 2>/dev/null || true
RUN mkdir -p /logs/verifier /logs/agent
RUN chmod -R 777 /testbed /logs
RUN git config --system --add safe.directory /testbed
