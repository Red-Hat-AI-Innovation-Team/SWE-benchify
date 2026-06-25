FROM python:3.11-slim

RUN apt-get update -qq && \
    apt-get install -y --no-install-recommends git patch build-essential && \
    rm -rf /var/lib/apt/lists/*

RUN pip install --no-cache-dir pytest

RUN git clone https://github.com/ansible/molecule.git /testbed && \
    cd /testbed && git checkout 1cbba7713710239734d6889358e603f4a02acf32 && \
    git branch -f main 1cbba7713710239734d6889358e603f4a02acf32

WORKDIR /testbed
RUN mkdir -p /logs/verifier /logs/agent
RUN chmod -R 777 /testbed /logs
RUN git config --system --add safe.directory /testbed
