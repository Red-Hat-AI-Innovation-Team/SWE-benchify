FROM ghcr.io/red-hat-ai-innovation-team/swe-benchify/grpc-go:a481b8f755bc

COPY patch.diff /tmp/patch.diff
RUN cd /testbed && git apply --reverse /tmp/patch.diff && rm /tmp/patch.diff

RUN mkdir -p /logs/verifier /logs/agent /logs/artifacts
