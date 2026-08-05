# Eval Server — Specification

The eval server is the asynchronous evaluation infrastructure used by the
optimization loop: it accepts a Factory workflow script (`my_swebench.py`) plus
a callback URL, runs train and test SWE-bench evaluations with that exact
script, and delivers the results (scores + zipped train logs) back to the
callback URL.

Source: `evaluation_infrastructure/eval_server/` package. Entry point:
`eval_server.main:app` (FastAPI).

## 1. Architecture

```
optimizer ──POST /jobs {script, callback_url}──▶ FastAPI app (uvicorn)
                                                       │
                                      202 {job_id, status} ◀─ immediate ack
                                                       │
                                          SQLite (eval-server.db)
                                               jobs table
                                                       │
                                              worker thread (FIFO, 1 at a time)
                                                       │
                          ┌────────────────────────────┼─────────────────────────┐
                          │ run train eval             │ run test eval           │
                          │ harbor run                 │ harbor run               │
                          │ benchmark-go-train         │ benchmark-go-test        │
                          └────────────┬───────────────┴────────────┬────────────┘
                                       │ train-eval.zip             │ test score
                                       ▼                             ▼
                        POST multipart {job_id, status, train_score, test_score,
                                        error} + logs=zip  ──▶ callback URL
```

Components:

| Module | Responsibility |
|---|---|
| `main.py` | FastAPI app; `create_app(db_path, jobs_root, runner, start_worker)` factory (dependency injection for tests); HTTP API |
| `db.py` | SQLite storage (stdlib `sqlite3`), jobs table, status transitions |
| `worker.py` | Background daemon thread; claims queued jobs FIFO, one at a time; runs the runner; delivers callbacks |
| `runner.py` | Executes train + test Harbor evaluations for a job; parses scores; builds the zip |
| `callback.py` | Multipart delivery of results to the callback URL with retries |

## 2. API contract

### `POST /jobs` — submit an eval job

Request body (JSON):

| Field | Type | Description |
|---|---|---|
| `script` | string | Full contents of the workflow script (must be valid Python, `ast.parse` checked; the Factory workflow must keep the name `my_swebench`, since the agent runs `factory workflow run my_swebench`) |
| `callback_url` | string | URL that must start with `http://` or `https://`; receives results when the job finishes |

Responses:

- `202 Accepted` → `{"job_id": "<12-hex-char-id>", "status": "queued"}` —
  the job is queued and the worker will pick it up; evaluation runs
  asynchronously.
- The `job_id` is generated server-side (`uuid.uuid4().hex[:12]`,
`eval_server/main.py`) and also names the job's working directory
(`server-jobs/<job_id>/`). It is not supplied by the caller.
- `400 Bad Request` → `detail` explains the problem: missing/invalid `script`,
  syntax error in the script, or invalid `callback_url`.
- `500` → failed to persist the job on disk.

The script is stored at `server-jobs/<job_id>/my_swebench.py`.

### `GET /jobs/{job_id}` — job status

`200` → JSON with `id`, `callback_url`, `status`, `created_at`, `started_at`,
`finished_at`, `train_score`, `test_score`, `error` (no script path).

`404` → unknown job.

There is no `GET /jobs` list endpoint.

## 3. Job lifecycle & statuses

| Status | Meaning |
|---|---|
| `queued` | Submitted, waiting for the worker (FIFO by `created_at`) |
| `running` | Worker claimed it; started_at set; eval in progress |
| `completed` | Train + test evals finished; scores stored; callback delivered (or attempted) |
| `failed` | Evaluation raised (e.g. harbor error, missing result.json, timeout); `error` set; callback delivered with `status=failed` |
| `callback_failed` | Evaluation finished (completed or failed) but the callback URL never accepted the results after all retries; results remain in the DB |

On server start the worker marks any stale `running` rows as `failed`
("interrupted by server restart").

## 4. Evaluation execution (`runner.py`)

Per job, the worker runs, in order:

1. **Train eval** — `uvx harbor run -p benchmark-go-train/harbor-tasks`
   with `--job-name eval-train-<job_id>`, output to
   `server-jobs/<job_id>/harbor-jobs/eval-train-<job_id>`.
2. **Zip** — the full train output dir is zipped to
   `server-jobs/<job_id>/train-eval.zip` (result.json, job.log, per-trial logs,
   agent sessions, verifier output, artifacts).
3. **Test eval** — same, against `benchmark-go-test/harbor-tasks`,
   `--job-name eval-test-<job_id>`.

Fixed eval configuration:

| Setting | Value |
|---|---|
| Agent | `my_factory:SwebenchFactoryCeo` |
| Model | `anthropic/claude-opus-4-6@default` |
| Concurrency | 4 (env `EVAL_CONCURRENCY`) |
| Task limit | unset = full benchmark (env `EVAL_LIMIT`; set 1 for smoke tests) |
| Subprocess timeout | 4 h (env `EVAL_TIMEOUT_SECONDS`) |

Environment for the subprocess: `PYTHONPATH=<repo root>`,
`GOOGLE_APPLICATION_CREDENTIALS=/tmp/gcp-creds.json`, plus the parent env.

### Workflow script mounting

`runner.create_compose_override` reads `vertex-creds.yaml`, replaces the
`/tmp/my_swebench.py` volume mount with the job's uploaded copy
(`server-jobs/<job_id>/my_swebench.py`), and writes a per-job
`server-jobs/<job_id>/compose.yaml`. This guarantees the eval runs the
submitted script, not whatever is checked out in the repo.

### Score parsing

For each eval: `server-jobs/<job_id>/harbor-jobs/eval-<split>-<job_id>/result.json`
→ first entry of `stats.evals.*.metrics[0].mean`. Raises a descriptive
`RuntimeError` if result.json is missing or contains no metrics.

## 5. Callback contract (`callback.py`)

When the job finishes, the worker POSTs a multipart/form-data request to
`callback_url`:

| Form field | Contents |
|---|---|
| `job_id` | Job ID |
| `status` | `completed` or `failed` |
| `train_score` | Train eval mean score (empty string if unavailable) |
| `test_score` | Test eval mean score (empty string if unavailable) |
| `error` | Error message (only present on failure) |
| `logs` | File upload `train-eval.zip` (train eval logs; absent if train failed before zipping) |

Delivery policy: up to 5 attempts with increasing backoff (10 s × attempt);
HTTP status must be 2xx. If all attempts fail, the job is marked
`callback_failed` — results stay in the DB and are still retrievable via
`GET /jobs/{job_id}`.

Note: only the **train** logs are zipped; the test eval output stays on the
server under `server-jobs/<job_id>/harbor-jobs/eval-test-*/` (the test score is
still reported).

## 6. Storage layout

```
server-jobs/<job_id>/
├── my_swebench.py          # uploaded workflow script
├── compose.yaml            # per-job docker compose override
├── train-eval.zip          # zipped train output (delivered via callback)
└── harbor-jobs/
    ├── eval-train-<job_id>/…   # full harbor train output
    └── eval-test-<job_id>/…    # full harbor test output

eval-server.db               # SQLite: jobs table
```

`jobs` schema:
`id TEXT PK, callback_url, script_path, status, created_at, started_at,
finished_at, train_score REAL, test_score REAL, error, results_json`.

## 7. Running the server

```bash
just serve   # uv run uvicorn eval_server.main:app --app-dir evaluation_infrastructure --host 0.0.0.0 --port 8000
```

Env knobs: `EVAL_CONCURRENCY` (default 4), `EVAL_LIMIT` (default unset),
`EVAL_TIMEOUT_SECONDS` (default 4 h).

## 8. Behavior notes / edge cases

- One job runs at a time (worker is a single thread); queued jobs run FIFO.
- A worker restart does not lose jobs: queued rows survive; stale `running`
  rows are failed.
- The callback is best-effort with retries; the DB is the source of truth.
- Harbor is invoked as `uvx harbor run`; it requires the same host
  prerequisites as the manual justfile workflow (podman/docker compose v2,
  DOCKER_HOST, GCP creds, Vertex model access).
