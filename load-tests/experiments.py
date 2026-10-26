"""Experiment-specific workload and starting-health requirements."""

EXPERIMENTS = {
    "baseline": {"mode": "constant", "members": 1},
    "scaled": {"mode": "constant", "members": 2},
    "elasticity": {"mode": "ramp", "members": 1},
    "failure": {"mode": "constant", "members": 2},
}
