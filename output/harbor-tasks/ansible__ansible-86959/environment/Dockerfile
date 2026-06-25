FROM python:3.11-slim

RUN apt-get update -qq && \
    apt-get install -y --no-install-recommends git patch build-essential && \
    rm -rf /var/lib/apt/lists/*

RUN pip install --no-cache-dir pytest

RUN git clone https://github.com/ansible/ansible.git /testbed && \
    cd /testbed && git checkout 57f4901faf65301b1abcbb19c3145a09ac0dfc7b && \
    git branch -f main 57f4901faf65301b1abcbb19c3145a09ac0dfc7b

WORKDIR /testbed
RUN pip install -e . 2>/dev/null || pip install . 2>/dev/null || true
RUN mkdir -p /logs/verifier /logs/agent
RUN chmod -R 777 /testbed /logs
RUN git config --system --add safe.directory /testbed
