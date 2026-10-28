"""Plot local k6 and CloudWatch evidence without contacting AWS."""

import argparse
import json
import math
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import pandas as pd


BIN_SECONDS = 10
CHARTS = ("throughput", "latency", "http_failures", "dropped_iterations", "cpu")


def load_run(directory: Path) -> dict:
    with (directory / "run.json").open(encoding="utf-8") as source:
        metadata = json.load(source)
    start = pd.to_datetime(metadata["test_start_utc"], utc=True)
    end = pd.to_datetime(metadata["test_end_utc"], utc=True)
    if pd.isna(start) or pd.isna(end) or end <= start:
        raise ValueError(f"Invalid test window in {directory / 'run.json'}")
    return {
        "directory": directory,
        "label": f"{metadata.get('experiment', 'run')}: {directory.name}",
        "start": start,
        "end": end,
        "k6": read_k6(directory / "k6.csv", start, end),
        "ec2": read_cpu(directory / "ec2_cpu.csv", start, end),
        "rds": read_cpu(directory / "rds_metrics.csv", start, end),
    }


def read_k6(path: Path, start, end) -> pd.DataFrame:
    columns = ["metric_name", "timestamp", "metric_value"]
    if not path.exists():
        print(f"Missing: {path}")
        return pd.DataFrame(columns=columns + ["time", "elapsed_min"])
    frame = pd.read_csv(path, usecols=columns)
    # k6 CSV has used both Unix seconds and Unix milliseconds.
    timestamps = pd.to_numeric(frame["timestamp"], errors="coerce")
    frame["time"] = pd.to_datetime(timestamps, unit="s", utc=True, errors="coerce")
    milliseconds = timestamps >= 1e11
    frame.loc[milliseconds, "time"] = pd.to_datetime(
        timestamps[milliseconds], unit="ms", utc=True, errors="coerce"
    )
    frame["metric_value"] = pd.to_numeric(frame["metric_value"], errors="coerce")
    frame = frame.loc[frame["time"].between(start, end)].copy()
    frame["elapsed_min"] = (frame["time"] - start).dt.total_seconds() / 60
    return frame


def read_cpu(path: Path, start, end) -> pd.DataFrame:
    columns = ["timestamp_utc", "resource_id", "metric", "statistic", "value", "unit"]
    if not path.exists():
        print(f"Missing: {path}")
        return pd.DataFrame(columns=columns + ["elapsed_min"])
    frame = pd.read_csv(path, usecols=columns)
    frame["timestamp_utc"] = pd.to_datetime(frame["timestamp_utc"], utc=True, errors="coerce")
    frame["value"] = pd.to_numeric(frame["value"], errors="coerce")
    frame = frame.loc[
        frame["timestamp_utc"].between(start.floor("min"), end.ceil("min"))
        & frame["metric"].eq("CPUUtilization")
        & frame["statistic"].eq("Average")
        & frame["unit"].eq("Percent")
    ].dropna(subset=["timestamp_utc", "value"]).copy()
    frame["elapsed_min"] = (frame["timestamp_utc"] - start).dt.total_seconds() / 60
    return frame


def binned(frame: pd.DataFrame, metric: str, statistic: str, duration_seconds: float) -> pd.Series:
    samples = frame.loc[frame["metric_name"].eq(metric)].dropna(subset=["time", "metric_value"])
    if samples.empty:
        return pd.Series(dtype=float)
    # Align bins to the run's UTC start rather than to the first observed sample.
    bucket = (samples["elapsed_min"] * 60 // BIN_SECONDS).astype(int)
    grouped = samples.groupby(bucket)["metric_value"]
    if statistic == "count":
        values = grouped.sum() / BIN_SECONDS
    elif statistic == "p95":
        values = grouped.quantile(0.95)
    else:
        values = grouped.sum()
    # Keep empty intervals as gaps rather than drawing a line across missing evidence.
    values = values.reindex(range(math.ceil(duration_seconds / BIN_SECONDS)))
    values.index = (values.index + 0.5) * BIN_SECONDS / 60
    return values


def plot_k6(runs: list[dict], metric: str, title: str, ylabel: str,
            statistic: str, output: Path) -> None:
    fig, axis = plt.subplots(figsize=(10, 5))
    plotted = False
    for run in runs:
        duration = (run["end"] - run["start"]).total_seconds()
        series = binned(run["k6"], metric, statistic, duration)
        if series.empty:
            print(f"No {metric} samples: {run['directory']}")
            continue
        axis.plot(series.index, series.values, label=run["label"])
        plotted = True
    if not plotted:
        axis.text(0.5, 0.5, "No metric samples available", ha="center", va="center",
                  transform=axis.transAxes)
    finish_plot(fig, axis, title, ylabel, runs, output, plotted)


def plot_cpu(runs: list[dict], output: Path) -> None:
    fig, axes = plt.subplots(2, 1, figsize=(10, 8), sharex=True)
    for axis, source, title in zip(axes, ("ec2", "rds"), ("Product EC2", "RDS")):
        plotted = False
        for run in runs:
            frame = run[source]
            for resource_id, series in frame.groupby("resource_id"):
                series = series.set_index("timestamp_utc")["value"].sort_index()
                minutes = pd.date_range(series.index.min(), series.index.max(), freq="min")
                series = series.reindex(minutes)
                elapsed_min = (series.index - run["start"]).total_seconds() / 60
                axis.plot(elapsed_min, series, marker="o", markersize=3,
                          label=f"{run['label']} / {resource_id}")
                plotted = True
            if frame.empty:
                print(f"No {source} CPU samples: {run['directory']}")
        if not plotted:
            axis.text(0.5, 0.5, "No CPU samples available", ha="center", va="center",
                      transform=axis.transAxes)
        axis.set_title(f"{title} CPUUtilization (CloudWatch Average, 60 s)")
        axis.set_ylabel("CPU utilisation (%)")
        axis.grid(alpha=0.3)
        if plotted:
            axis.legend(fontsize=7)
    axes[-1].set_xlabel("Minutes from k6 test start (UTC)")
    fig.suptitle("Application and RDS CPU by run; minute buckets may overlap test bounds")
    add_windows(fig, runs)
    fig.tight_layout(rect=(0, 0.04, 1, 1))
    fig.savefig(output, dpi=180)
    plt.close(fig)


def finish_plot(fig, axis, title, ylabel, runs, output, plotted):
    axis.set_title(f"{title} (10 s bins)")
    axis.set_xlabel("Minutes from k6 test start (UTC)")
    axis.set_ylabel(ylabel)
    axis.grid(alpha=0.3)
    if plotted:
        axis.legend(fontsize=8)
    add_windows(fig, runs)
    fig.tight_layout(rect=(0, 0.04, 1, 1))
    fig.savefig(output, dpi=180)
    plt.close(fig)


def add_windows(fig, runs):
    windows = " | ".join(
        f"{run['directory'].name}: {run['start'].strftime('%Y-%m-%d %H:%M:%S')}–"
        f"{run['end'].strftime('%H:%M:%S')} UTC" for run in runs
    )
    fig.text(0.01, 0.01, windows, fontsize=7)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("runs", type=Path, nargs="+", help="One or more local evidence run directories")
    parser.add_argument("--output-dir", type=Path, required=True, help="New directory for PNG charts")
    args = parser.parse_args()
    if args.output_dir.exists():
        parser.error(f"Output directory already exists: {args.output_dir}")
    try:
        runs = [load_run(path) for path in args.runs]
    except (OSError, ValueError, KeyError) as error:
        parser.error(str(error))
    args.output_dir.mkdir(parents=True)
    plot_k6(runs, "http_reqs", "Completed HTTP requests", "Requests/s", "count",
            args.output_dir / "throughput.png")
    plot_k6(runs, "http_req_duration", "Client HTTP response latency p95",
            "Duration (ms)", "p95", args.output_dir / "latency.png")
    plot_k6(runs, "http_req_failed", "HTTP failures", "Failed requests / 10 s", "sum",
            args.output_dir / "http_failures.png")
    plot_k6(runs, "dropped_iterations", "Dropped iterations", "Dropped iterations / 10 s", "sum",
            args.output_dir / "dropped_iterations.png")
    plot_cpu(runs, args.output_dir / "cpu.png")
    print(f"Saved {len(CHARTS)} PNG charts to {args.output_dir}")


if __name__ == "__main__":
    main()
