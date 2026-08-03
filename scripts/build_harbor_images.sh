#!/usr/bin/env bash
set -euo pipefail

# Build Docker images for each repo in the 847-instance dataset.
# Each image has the repo pre-cloned at merge_commit with go mod download done.
#
# Usage:
#   bash scripts/build_harbor_images.sh                    # Build all
#   bash scripts/build_harbor_images.sh --push             # Build + push to GHCR
#   bash scripts/build_harbor_images.sh --repo grpc/grpc-go  # Build one

BASE_IMAGE="ghcr.io/red-hat-ai-innovation-team/swe-benchify/swebenchify-synthesis:streaming"
REGISTRY="ghcr.io/red-hat-ai-innovation-team/swe-benchify"
DATASET="data/swebenchify-847.jsonl"
PUSH=false
SINGLE_REPO=""

while [[ $# -gt 0 ]]; do
  case $1 in
    --push) PUSH=true; shift ;;
    --repo) SINGLE_REPO="$2"; shift 2 ;;
    *) echo "Unknown: $1"; exit 1 ;;
  esac
done

# Extract unique repo+commit pairs
repos=$(python3 -c "
import json
from collections import defaultdict
seen = set()
with open('$DATASET') as f:
    for line in f:
        d = json.loads(line.strip())
        repo = d['repo']
        commit = d.get('merge_commit') or d.get('base_commit')
        key = f'{repo}|{commit}'
        if key not in seen:
            seen.add(key)
            print(f'{repo}|{commit}')
")

echo "=== Building Harbor images ==="

while IFS='|' read -r repo commit; do
  if [ -n "$SINGLE_REPO" ] && [ "$repo" != "$SINGLE_REPO" ]; then
    continue
  fi

  slug=$(echo "$repo" | tr '/' '-')
  image_tag="${REGISTRY}/harbor-${slug}:${commit:0:12}"

  echo "--- $repo @ ${commit:0:12} ---"
  echo "  Image: $image_tag"

  # Build with inline Dockerfile
  docker build --platform linux/amd64 -t "$image_tag" -f - . << DOCKERFILE
FROM ${BASE_IMAGE}

# Clone repo at the specific commit
RUN git clone --depth=50 https://github.com/${repo}.git /testbed && \\
    cd /testbed && \\
    git checkout ${commit} || (git fetch --unshallow && git checkout ${commit}) && \\
    git config --global --add safe.directory /testbed

# Pre-download Go dependencies
ENV HOME=/tmp GOPATH=/tmp/go GOMODCACHE=/tmp/go/mod CGO_ENABLED=0
RUN cd /testbed && go mod download 2>/dev/null || true

WORKDIR /testbed
DOCKERFILE

  echo "  Built: $image_tag"

  if $PUSH; then
    docker push "$image_tag"
    echo "  Pushed: $image_tag"
  fi

done <<< "$repos"

echo
echo "=== Done ==="
if ! $PUSH; then
  echo "Run with --push to push to GHCR"
fi

# Update the dataset with image_name field
python3 -c "
import json

with open('$DATASET') as f:
    instances = [json.loads(l.strip()) for l in f if l.strip()]

for inst in instances:
    repo = inst['repo']
    commit = inst.get('merge_commit') or inst.get('base_commit')
    slug = repo.replace('/', '-')
    inst['image_name'] = '${REGISTRY}/harbor-' + slug + ':' + commit[:12]

with open('$DATASET', 'w') as f:
    for inst in instances:
        f.write(json.dumps(inst) + '\n')

print(f'Updated {len(instances)} instances with image_name')
"
