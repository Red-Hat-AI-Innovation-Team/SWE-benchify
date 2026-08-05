# submit_eval.py — Specification

The client-side counterpart of the eval server. It is the one-shot command the
optimization loop uses to evaluate a workflow version: submit a workflow script
to the eval server, wait until the evaluation completes, save the delivered
results to the filesystem, and print the results path so the caller (e.g. an
optimizer) can read them.

Source: `evaluation_infrastructure/submit_eval.py`. Single file, standard
library + `requests`, `uvicorn`, `fastapi`.

## 1. Usage

```
python evaluation_infrastructure/submit_eval.py <workflow_script.py> [options]
```

| Option | Default | Description |
|---|---|---|
| `script` (positional) | — | Path to the workflow script to evaluate (e.g. `my_swebench.py`) |
| `--eval-server` | `http://localhost:8000` | Base URL of the eval server |
| `--output-dir` | `./eval-results` | Where results are saved |
| `--timeout` | `86400` (24 h) | Seconds to wait for results before giving up |
| `--port` | `0` (ephemeral) | Local callback receiver port |

## 2. Flow

1. **Start the callback receiver** — a FastAPI app listening on
   `127.0.0.1:<port>` (uvicorn in a background thread). With `--port 0` the OS
   assigns a free port; the actual port is printed.
2. **Submit** — POSTs `{"script": <file contents>, "callback_url":
   http://127.0.0.1:<port>/callback}` to the eval server; prints
   `Submitted job <job_id> ...`.
3. **Wait** — blocks until the callback arrives or `--timeout` elapses.
   Every 900 s (15 min) it polls `GET /jobs/<job_id>` on the eval server and
   prints status transitions (informational only; results come from the
   callback).
4. **Save results** — when the callback arrives, it saves the delivered zip,
   extracts it, writes `summary.json`, prints `Results saved to: <path>`,
   and exits.

Stdout/stderr are line-buffered so progress is visible when logging to a file.

## 3. Output layout

```
<output-dir>/<job_id>/
├── summary.json          # machine-readable result summary (see below)
├── train-eval.zip        # the delivered zip (full train eval output)
└── train-eval/           # extracted zip contents (result.json, job.log,
                          #   per-trial agent logs, sessions, verifier output,
                          #   candidate patch)
```

### summary.json schema

```json
{
  "job_id": "<job id>",
  "status": "completed",
  "train_score": 1.0,
  "test_score": 1.0,
  "error": null,
  "received_at": "2026-08-04T15:59:10.951849+00:00",
  "zip": "/abs/path/to/<output-dir>/<job_id>/train-eval.zip",
  "extracted_dir": "/abs/path/to/<output-dir>/<job_id>/train-eval",
  "summary_path": "/abs/path/to/<output-dir>/<job_id>/summary.json"
}
```

- `status`: `completed`, `failed`, or `callback_failed` (mirrors the eval
  server's delivered status).
- `train_score` / `test_score`: floats, or `null` if the eval never produced
  them.
- `error`: error message string when the eval failed, otherwise `null`.

## 4. Exit codes

| Code | Meaning |
|---|---|
| 0 | Callback received and results saved; evaluation completed successfully |
| 1 | Callback received but the evaluation failed (results still saved; error in summary.json), results could not be saved, or the timeout elapsed with no callback |
| 2 | Submission error: script file missing/unreadable, eval server unreachable or rejected the job, callback receiver failed to start |

## 5. Integration with the optimizer

The optimizer drives an iteration like this:

```
1. write <version>.py            # new workflow version
2. run:  python evaluation_infrastructure/submit_eval.py <version>.py --eval-server http://<host>:<port>
3. capture stdout, parse the "Results saved to: <path>" line
4. read <path>/summary.json      # train_score, test_score, status, error
5. read <path>/train-eval/       # logs: factory-ceo.txt, sessions, verifier
```

Requirements for a clean iteration:

- The eval server must be reachable from where the client runs (same host in
  the current setup, since the callback URL is `127.0.0.1:<random port>`).
- The workflow script submitted must keep the Factory workflow name
  `my_swebench` (the agent runs `factory workflow run my_swebench` regardless
  of the file name).
- A failed eval exits with code 1 — treat that as an iteration result with
  `summary.json` in hand, not a crash.

## 6. Notes

- The callback receiver handles a single callback; it exits after the first
  successful delivery.
- If the callback never arrives (eval server down, job stuck), the client
  exits 1 after `--timeout`; the job may still be running on the eval server
  and can be queried later with `GET /jobs/<job_id>`.
