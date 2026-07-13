"""Test mechanical stages (1-2) on pallets/flask and compare against SWE-bench fixture."""

import json
import logging
import os
import sys

logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")

from swebenchify.collector import collect_prs, save_prs  # noqa: E402
from swebenchify.extractor import extract_all, save_candidates  # noqa: E402
from swebenchify.models import Repository  # noqa: E402

token = os.environ.get("GITHUB_TOKEN")
if not token:
    print("Set GITHUB_TOKEN first")
    sys.exit(1)

repo = Repository(full_name="pallets/flask", access_token=token)

# SWE-bench Flask instances span 2021-05 to 2023-04.
# Use a cutoff that covers this range with some margin.
PR_AFTER = "2021-01-01T00:00:00Z"
PR_BEFORE = "2023-06-01T00:00:00Z"

# Stage 1: Collect PRs
print(f"\n=== Stage 1: Collecting PRs ({PR_AFTER} to {PR_BEFORE}) ===")
prs = collect_prs(repo, pr_after=PR_AFTER, pr_before=PR_BEFORE)
print(f"Collected {len(prs)} candidate PRs")
os.makedirs("output", exist_ok=True)
save_prs(prs, "output/flask-prs.jsonl")

# Stage 2: Extract patches
print("\n=== Stage 2: Extracting patches ===")
candidates = extract_all(prs, github_token=token)
print(f"Extracted {len(candidates)} candidates")
save_candidates(candidates, "output/flask-candidates.jsonl")

viable = [c for c in candidates if c.patch and c.test_patch and c.problem_statement]
print(f"Viable (has patch + test_patch + problem_statement): {len(viable)}")

# Compare against SWE-bench fixture
print("\n=== Comparing against SWE-bench fixture ===")
fixture_path = "tests/fixtures/swebench_flask.jsonl"
fixture_instances = []
with open(fixture_path) as f:
    for line in f:
        fixture_instances.append(json.loads(line))

fixture_ids = {inst["instance_id"] for inst in fixture_instances}
our_ids = {c.instance_id for c in viable}

overlap = fixture_ids & our_ids
only_fixture = fixture_ids - our_ids
only_ours = our_ids - fixture_ids

print(f"SWE-bench fixture: {len(fixture_ids)} instances")
print(f"Our viable output: {len(our_ids)} instances")
print(f"Overlap: {len(overlap)} ({100*len(overlap)/len(fixture_ids):.0f}%)")

if overlap:
    print(f"\nMatched: {sorted(overlap)}")
if only_fixture:
    print(f"\nIn SWE-bench but not ours: {sorted(only_fixture)}")
    # Diagnose: check if we collected the PR but it wasn't viable
    for missing_id in sorted(only_fixture):
        pr_num = int(missing_id.rsplit("-", 1)[1])
        collected = any(p.pr_number == pr_num for p in prs)
        extracted = any(c.instance_id == missing_id for c in candidates)
        has_patch = has_test = has_ps = False
        for c in candidates:
            if c.instance_id == missing_id:
                has_patch = bool(c.patch)
                has_test = bool(c.test_patch)
                has_ps = bool(c.problem_statement)
                break
        print(f"  {missing_id}: collected={collected} extracted={extracted} patch={has_patch} test_patch={has_test} problem={has_ps}")
if only_ours:
    print(f"\nIn ours but not SWE-bench ({len(only_ours)} extra): {sorted(only_ours)[:10]}{'...' if len(only_ours) > 10 else ''}")
