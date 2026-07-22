version := "1"

_run run_number:
  GOOGLE_APPLICATION_CREDENTIALS=/tmp/gcp-creds.json \
  PYTHONPATH=. \
  uvx harbor run -p ./benchmark-python/harbor-tasks \
    --agent "my_factory:SwebenchFactoryCeo" \
    --model "anthropic/claude-opus-4-6@default" \
    -n 4 \
    --job-name eval-python-factory-v{{version}}-run-{{run_number}} \
    --extra-docker-compose vertex-creds.yaml

run-1: (_run "1")

run-2: (_run "2")

run-3: (_run "3")

run-all: run-1 run-2 run-3
  #!/usr/bin/env python3
  import json, glob
  scores = [next(iter(json.load(open(f))["stats"]["evals"].values()))["metrics"][0]["mean"] for f in sorted(glob.glob("jobs/eval-python-factory-v{{version}}-run-*/result.json"))]
  print("Mean across %d runs: %.4f  %s" % (len(scores), sum(scores)/len(scores), [round(s,4) for s in scores]))

