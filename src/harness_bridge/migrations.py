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
