"""Additive coordination schema; legacy task/attempt contracts remain unchanged."""

COORDINATION_SCHEMA = """
CREATE TABLE projects (
    project_id TEXT PRIMARY KEY,
    repo_identity TEXT NOT NULL UNIQUE,
    repo_path TEXT NOT NULL,
    created_at TEXT NOT NULL
);
CREATE TABLE goals (
    goal_id TEXT PRIMARY KEY,
    project_id TEXT NOT NULL REFERENCES projects(project_id),
    idempotency_key TEXT NOT NULL UNIQUE,
    request_digest TEXT NOT NULL,
    spec_json TEXT NOT NULL,
    base_sha TEXT NOT NULL,
    binding_id TEXT NOT NULL,
    advisor_epoch INTEGER NOT NULL CHECK(advisor_epoch >= 1),
    advisor_json TEXT NOT NULL,
    create_receipt TEXT NOT NULL,
    created_at TEXT NOT NULL
);
CREATE TABLE goal_tasks (
    task_id TEXT PRIMARY KEY REFERENCES tasks(task_id),
    goal_id TEXT NOT NULL REFERENCES goals(goal_id)
);
CREATE INDEX goal_tasks_by_goal ON goal_tasks(goal_id);
CREATE TABLE advisor_takeovers (
    goal_id TEXT NOT NULL REFERENCES goals(goal_id),
    idempotency_key TEXT NOT NULL,
    request_digest TEXT NOT NULL,
    receipt_json TEXT NOT NULL,
    PRIMARY KEY(goal_id, idempotency_key)
);
CREATE TABLE goal_events (
    seq INTEGER PRIMARY KEY AUTOINCREMENT,
    goal_id TEXT NOT NULL REFERENCES goals(goal_id),
    type TEXT NOT NULL,
    advisor_epoch INTEGER NOT NULL,
    payload TEXT NOT NULL,
    created_at TEXT NOT NULL
);
CREATE INDEX goal_events_by_goal ON goal_events(goal_id, seq);
"""

PLANNING_SCHEMA = """
CREATE TABLE goal_controls (
    goal_id TEXT PRIMARY KEY REFERENCES goals(goal_id),
    paused INTEGER NOT NULL DEFAULT 0 CHECK(paused IN (0,1)),
    termination TEXT CHECK(termination IN ('cancel','fail')),
    reason TEXT NOT NULL
);
CREATE TABLE goal_control_requests (
    goal_id TEXT NOT NULL REFERENCES goals(goal_id),
    idempotency_key TEXT NOT NULL,
    request_digest TEXT NOT NULL,
    receipt_json TEXT NOT NULL,
    PRIMARY KEY(goal_id,idempotency_key)
);
CREATE TABLE child_plans (
    child_id TEXT PRIMARY KEY,
    goal_id TEXT NOT NULL REFERENCES goals(goal_id),
    child_key TEXT NOT NULL,
    spec_json TEXT NOT NULL,
    spec_digest TEXT NOT NULL,
    task_id TEXT UNIQUE REFERENCES tasks(task_id),
    created_at TEXT NOT NULL,
    UNIQUE(goal_id,child_key)
);
CREATE TABLE child_dependencies (
    child_id TEXT NOT NULL REFERENCES child_plans(child_id),
    dependency_id TEXT NOT NULL REFERENCES child_plans(child_id),
    PRIMARY KEY(child_id,dependency_id),
    CHECK(child_id <> dependency_id)
);
CREATE TABLE plan_batches (
    goal_id TEXT NOT NULL REFERENCES goals(goal_id),
    idempotency_key TEXT NOT NULL,
    request_digest TEXT NOT NULL,
    receipt_json TEXT NOT NULL,
    PRIMARY KEY(goal_id,idempotency_key)
);
"""

BASELINE_SCHEMA = """
CREATE TABLE approved_snapshots (
    task_id TEXT PRIMARY KEY REFERENCES tasks(task_id),
    review_id TEXT NOT NULL REFERENCES reviews(review_id),
    record_json TEXT NOT NULL,
    record_digest TEXT NOT NULL
);
CREATE TABLE child_baselines (
    child_id TEXT PRIMARY KEY REFERENCES child_plans(child_id),
    record_json TEXT NOT NULL,
    record_digest TEXT NOT NULL
);
"""

PREPARATION_SCHEMA = """
CREATE TABLE preparation_runs (
    preparation_id TEXT PRIMARY KEY,
    task_id TEXT NOT NULL REFERENCES tasks(task_id),
    idempotency_key TEXT NOT NULL,
    status TEXT NOT NULL,
    exit_confirmed INTEGER CHECK(exit_confirmed IN (0,1)),
    record_json TEXT NOT NULL,
    record_digest TEXT NOT NULL,
    created_at TEXT NOT NULL,
    UNIQUE(task_id,idempotency_key)
);
CREATE INDEX preparation_by_task ON preparation_runs(task_id,created_at);
CREATE TABLE preparation_resources (
    project_id TEXT NOT NULL REFERENCES projects(project_id),
    name TEXT NOT NULL,
    task_id TEXT NOT NULL REFERENCES tasks(task_id),
    preparation_id TEXT NOT NULL REFERENCES preparation_runs(preparation_id),
    PRIMARY KEY(project_id,name),
    UNIQUE(name)
);
"""

WORKER_SCHEMA = """
CREATE TABLE worker_jobs (
    job_id TEXT PRIMARY KEY,
    task_id TEXT NOT NULL REFERENCES tasks(task_id),
    attempt_id TEXT NOT NULL UNIQUE REFERENCES attempts(attempt_id),
    idempotency_key TEXT NOT NULL,
    request_digest TEXT NOT NULL,
    execution_json TEXT NOT NULL,
    execution_digest TEXT NOT NULL,
    phase TEXT NOT NULL CHECK(phase IN ('reserved','claimed','finished','abandoned','recovered')),
    error_code TEXT,
    created_at TEXT NOT NULL,
    ended_at TEXT,
    UNIQUE(task_id,idempotency_key)
);
"""

INTEGRATION_SCHEMA = """
CREATE TABLE integrations (
    integration_id TEXT PRIMARY KEY,
    goal_id TEXT NOT NULL REFERENCES goals(goal_id),
    idempotency_key TEXT NOT NULL,
    request_digest TEXT NOT NULL,
    spec_json TEXT NOT NULL,
    record_json TEXT NOT NULL,
    record_digest TEXT NOT NULL,
    created_at TEXT NOT NULL,
    UNIQUE(goal_id,idempotency_key)
);
CREATE INDEX integrations_by_goal ON integrations(goal_id,created_at);
"""

INTEGRATION_CHECK_SCHEMA = """
CREATE TABLE integration_verifications (
    run_id TEXT PRIMARY KEY,
    integration_id TEXT NOT NULL REFERENCES integrations(integration_id),
    idempotency_key TEXT NOT NULL,
    status TEXT NOT NULL,
    exit_confirmed INTEGER CHECK(exit_confirmed IN (0,1)),
    cancel_requested INTEGER NOT NULL DEFAULT 0 CHECK(cancel_requested IN (0,1)),
    record_json TEXT NOT NULL,
    record_digest TEXT NOT NULL,
    created_at TEXT NOT NULL,
    UNIQUE(integration_id,idempotency_key)
);
CREATE TABLE integration_reviews (
    review_id TEXT PRIMARY KEY,
    integration_id TEXT NOT NULL REFERENCES integrations(integration_id),
    idempotency_key TEXT NOT NULL,
    request_digest TEXT NOT NULL,
    record_json TEXT NOT NULL,
    record_digest TEXT NOT NULL,
    created_at TEXT NOT NULL,
    UNIQUE(integration_id,idempotency_key)
);
"""

DELIVERY_SCHEMA = """
CREATE TABLE deliveries (
    delivery_id TEXT PRIMARY KEY,
    goal_id TEXT NOT NULL REFERENCES goals(goal_id),
    project_id TEXT NOT NULL REFERENCES projects(project_id),
    idempotency_key TEXT NOT NULL,
    request_digest TEXT NOT NULL,
    branch TEXT NOT NULL COLLATE NOCASE,
    status TEXT NOT NULL CHECK(status IN ('prepared','delivered','aborted')),
    record_json TEXT NOT NULL,
    record_digest TEXT NOT NULL,
    created_at TEXT NOT NULL,
    UNIQUE(goal_id,idempotency_key)
);
CREATE UNIQUE INDEX active_delivery_per_goal ON deliveries(goal_id) WHERE status<>'aborted';
CREATE UNIQUE INDEX reserved_delivery_branch ON deliveries(project_id,branch)
    WHERE status<>'aborted';
"""

MIGRATIONS = {
    2: COORDINATION_SCHEMA,
    3: PLANNING_SCHEMA,
    4: BASELINE_SCHEMA,
    5: PREPARATION_SCHEMA,
    6: WORKER_SCHEMA,
    7: INTEGRATION_SCHEMA,
    8: INTEGRATION_CHECK_SCHEMA,
    9: DELIVERY_SCHEMA,
}
