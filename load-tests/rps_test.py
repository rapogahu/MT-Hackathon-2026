#!/usr/bin/env python3
"""Open-model HTTP load test for the MTTECH forecast API.

The script intentionally uses only the Python standard library so the load
generator can run outside the measured service container without installing
project dependencies.
"""

from __future__ import annotations

import argparse
import concurrent.futures
import datetime as dt
import http.client
import json
import math
import random
import statistics
import subprocess
import threading
import time
from collections import Counter, defaultdict
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any
from urllib.parse import urlencode, urlsplit
from urllib.request import urlopen


@dataclass(frozen=True)
class RequestResult:
    endpoint: str
    status: int
    latency_ms: float
    scheduling_delay_ms: float
    bytes_received: int
    error: str | None
    completed_at: float


@dataclass(frozen=True)
class ResourceSample:
    timestamp: str
    cpu_percent: float
    memory_mib: float
    memory_percent: float


class PersistentHttpClient:
    """One persistent HTTP connection per worker thread."""

    def __init__(self, base_url: str, timeout: float):
        parsed = urlsplit(base_url)
        if parsed.scheme not in {"http", "https"} or not parsed.hostname:
            raise ValueError("base URL must start with http:// or https://")

        self.scheme = parsed.scheme
        self.host = parsed.hostname
        self.port = parsed.port
        self.base_path = parsed.path.rstrip("/")
        self.timeout = timeout
        self.local = threading.local()

    def _connection(self) -> http.client.HTTPConnection:
        connection = getattr(self.local, "connection", None)
        if connection is None:
            connection_class = (
                http.client.HTTPSConnection
                if self.scheme == "https"
                else http.client.HTTPConnection
            )
            connection = connection_class(
                self.host,
                self.port,
                timeout=self.timeout,
            )
            self.local.connection = connection
        return connection

    def get(self, path: str, scheduled_at: float, endpoint: str) -> RequestResult:
        started_at = time.perf_counter()
        status = 0
        body = b""
        error = None
        try:
            connection = self._connection()
            connection.request(
                "GET",
                f"{self.base_path}{path}",
                headers={"Accept": "application/json"},
            )
            response = connection.getresponse()
            status = response.status
            body = response.read()
            if status < 200 or status >= 400:
                error = f"HTTP {status}"
        except Exception as exc:  # Network failures are part of load-test results.
            error = f"{type(exc).__name__}: {exc}"
            connection = getattr(self.local, "connection", None)
            if connection is not None:
                connection.close()
                self.local.connection = None

        completed_at = time.perf_counter()
        return RequestResult(
            endpoint=endpoint,
            status=status,
            latency_ms=(completed_at - started_at) * 1000,
            scheduling_delay_ms=max(0.0, (started_at - scheduled_at) * 1000),
            bytes_received=len(body),
            error=error,
            completed_at=completed_at,
        )


class DockerMonitor(threading.Thread):
    def __init__(self, container: str, stop_event: threading.Event):
        super().__init__(daemon=True)
        self.container = container
        self.stop_event = stop_event
        self.samples: list[ResourceSample] = []
        self.warning: str | None = None

    def run(self) -> None:
        while not self.stop_event.is_set():
            try:
                process = subprocess.run(
                    [
                        "docker",
                        "stats",
                        "--no-stream",
                        "--format",
                        "{{json .}}",
                        self.container,
                    ],
                    capture_output=True,
                    text=True,
                    timeout=5,
                    check=True,
                )
                payload = json.loads(process.stdout.strip())
                used_memory = payload["MemUsage"].split("/")[0].strip()
                self.samples.append(
                    ResourceSample(
                        timestamp=dt.datetime.now(dt.timezone.utc).isoformat(),
                        cpu_percent=_parse_percent(payload["CPUPerc"]),
                        memory_mib=_to_mib(used_memory),
                        memory_percent=_parse_percent(payload["MemPerc"]),
                    )
                )
            except Exception as exc:
                self.warning = f"Docker resource monitoring unavailable: {exc}"
                return
            self.stop_event.wait(1.0)


def _parse_percent(value: str) -> float:
    return float(value.strip().rstrip("%"))


def _to_mib(value: str) -> float:
    units = {
        "B": 1 / (1024 * 1024),
        "KiB": 1 / 1024,
        "MiB": 1,
        "GiB": 1024,
        "KB": 1000 / (1024 * 1024),
        "MB": 1_000_000 / (1024 * 1024),
        "GB": 1_000_000_000 / (1024 * 1024),
    }
    compact = value.replace(" ", "")
    for unit in sorted(units, key=len, reverse=True):
        if compact.endswith(unit):
            return float(compact[: -len(unit)]) * units[unit]
    raise ValueError(f"unknown memory unit: {value}")


def _json_get(url: str, timeout: float) -> dict[str, Any]:
    with urlopen(url, timeout=timeout) as response:
        return json.load(response)


def discover_workload(base_url: str, timeout: float, seed: int) -> list[tuple[str, str]]:
    runs = _json_get(f"{base_url.rstrip('/')}/api/forecast/runs", timeout)
    run_id = runs["active_run_id"]
    metadata = next(run for run in runs["runs"] if run["run_id"] == run_id)
    routes = [str(route) for route in metadata["routes"]]
    start = dt.date.fromisoformat(metadata["forecast_start"])
    end = dt.date.fromisoformat(metadata["forecast_end"])
    if not routes or start > end:
        raise RuntimeError("forecast metadata contains no routes or valid dates")

    random_generator = random.Random(seed)
    workload: list[tuple[str, str]] = []
    day_count = (end - start).days

    # A deterministic pool is reused cyclically, avoiding random-number overhead
    # while the measured phase is running.
    for _ in range(10_000):
        route = random_generator.choice(routes)
        date_value = start + dt.timedelta(days=random_generator.randint(0, day_count))
        path = "/api/forecast/point?" + urlencode(
            {
                "run_id": run_id,
                "route": route,
                "date": date_value.isoformat(),
                "hour": random_generator.randint(0, 23),
            }
        )
        workload.append(("forecast_point", path))
    return workload


def run_phase(
    client: PersistentHttpClient,
    workload: list[tuple[str, str]],
    rps: float,
    duration: float,
    workers: int,
) -> tuple[list[RequestResult], float]:
    total = max(1, math.floor(rps * duration))
    interval = 1.0 / rps
    started_at = time.perf_counter()
    futures: list[concurrent.futures.Future[RequestResult]] = []

    with concurrent.futures.ThreadPoolExecutor(max_workers=workers) as executor:
        for index in range(total):
            scheduled_at = started_at + index * interval
            remaining = scheduled_at - time.perf_counter()
            if remaining > 0:
                time.sleep(remaining)
            endpoint, path = workload[index % len(workload)]
            futures.append(
                executor.submit(client.get, path, scheduled_at, endpoint)
            )
        results = [future.result() for future in futures]

    finished_at = max(result.completed_at for result in results)
    return results, finished_at - started_at


def percentile(values: list[float], value: float) -> float:
    if not values:
        return 0.0
    ordered = sorted(values)
    rank = max(0, math.ceil(value / 100 * len(ordered)) - 1)
    return ordered[rank]


def summarize(
    results: list[RequestResult],
    elapsed: float,
    target_rps: float,
    p95_limit_ms: float,
    max_error_rate: float,
    min_rps_ratio: float,
    resources: list[ResourceSample],
    allocated_cpus: float,
) -> dict[str, Any]:
    latencies = [result.latency_ms for result in results]
    errors = [result for result in results if result.error]
    actual_rps = len(results) / elapsed
    error_rate = len(errors) / len(results) * 100
    endpoint_results: dict[str, list[RequestResult]] = defaultdict(list)
    for result in results:
        endpoint_results[result.endpoint].append(result)

    checks = {
        "rps": actual_rps >= target_rps * min_rps_ratio,
        "p95": percentile(latencies, 95) <= p95_limit_ms,
        "errors": error_rate <= max_error_rate,
    }
    resource_summary: dict[str, Any] | None = None
    if resources:
        raw_cpu = [sample.cpu_percent for sample in resources]
        memory = [sample.memory_mib for sample in resources]
        resource_summary = {
            "samples": len(resources),
            "cpu_percent_raw_avg": round(statistics.fmean(raw_cpu), 2),
            "cpu_percent_raw_max": round(max(raw_cpu), 2),
            "cpu_percent_of_allocation_avg": round(
                statistics.fmean(raw_cpu) / allocated_cpus, 2
            ),
            "cpu_percent_of_allocation_max": round(max(raw_cpu) / allocated_cpus, 2),
            "memory_mib_first": round(memory[0], 2),
            "memory_mib_last": round(memory[-1], 2),
            "memory_mib_max": round(max(memory), 2),
            "memory_growth_mib": round(memory[-1] - memory[0], 2),
        }

    return {
        "passed": all(checks.values()),
        "checks": checks,
        "requests": len(results),
        "elapsed_seconds": round(elapsed, 3),
        "target_rps": target_rps,
        "actual_rps": round(actual_rps, 2),
        "errors": len(errors),
        "error_rate_percent": round(error_rate, 3),
        "latency_ms": {
            "p50": round(percentile(latencies, 50), 2),
            "p95": round(percentile(latencies, 95), 2),
            "p99": round(percentile(latencies, 99), 2),
            "max": round(max(latencies), 2),
        },
        "scheduling_delay_ms_p95": round(
            percentile([result.scheduling_delay_ms for result in results], 95), 2
        ),
        "received_mib": round(
            sum(result.bytes_received for result in results) / 1024 / 1024, 2
        ),
        "statuses": dict(sorted(Counter(result.status for result in results).items())),
        "endpoints": {
            name: {
                "requests": len(items),
                "p95_ms": round(percentile([item.latency_ms for item in items], 95), 2),
                "errors": sum(item.error is not None for item in items),
            }
            for name, items in sorted(endpoint_results.items())
        },
        "resources": resource_summary,
        "sample_errors": [asdict(item) for item in errors[:5]],
    }


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Measure forecast API RPS and latency")
    parser.add_argument("--url", default="http://127.0.0.1:8000")
    parser.add_argument("--rps", type=float, default=300)
    parser.add_argument("--duration", type=float, default=60)
    parser.add_argument("--warmup", type=float, default=10)
    parser.add_argument("--workers", type=int, default=256)
    parser.add_argument("--timeout", type=float, default=5)
    parser.add_argument("--p95-ms", type=float, default=300)
    parser.add_argument("--max-error-rate", type=float, default=1.0)
    parser.add_argument("--min-rps-ratio", type=float, default=0.95)
    parser.add_argument("--allocated-cpus", type=float, default=2.0)
    parser.add_argument("--container", default="mttech-backend")
    parser.add_argument("--no-docker-stats", action="store_true")
    parser.add_argument("--seed", type=int, default=42)
    parser.add_argument("--json", type=Path, help="write the full report to this file")
    args = parser.parse_args()
    if min(args.rps, args.duration, args.workers, args.timeout, args.allocated_cpus) <= 0:
        parser.error("rps, duration, workers, timeout and allocated-cpus must be positive")
    return args


def main() -> int:
    args = parse_args()
    base_url = args.url.rstrip("/")
    print(f"Discovering workload from {base_url} ...")
    try:
        workload = discover_workload(base_url, args.timeout, args.seed)
    except Exception as exc:
        print(f"ERROR: API discovery failed: {exc}")
        return 2

    client = PersistentHttpClient(base_url, args.timeout)
    if args.warmup > 0:
        print(f"Warm-up: {args.rps:g} RPS for {args.warmup:g}s")
        run_phase(client, workload, args.rps, args.warmup, args.workers)

    stop_monitor = threading.Event()
    monitor = None
    if not args.no_docker_stats:
        monitor = DockerMonitor(args.container, stop_monitor)
        monitor.start()

    print(f"Measurement: {args.rps:g} RPS for {args.duration:g}s")
    results, elapsed = run_phase(
        client, workload, args.rps, args.duration, args.workers
    )
    stop_monitor.set()
    if monitor is not None:
        monitor.join(timeout=6)

    report = summarize(
        results=results,
        elapsed=elapsed,
        target_rps=args.rps,
        p95_limit_ms=args.p95_ms,
        max_error_rate=args.max_error_rate,
        min_rps_ratio=args.min_rps_ratio,
        resources=monitor.samples if monitor else [],
        allocated_cpus=args.allocated_cpus,
    )
    if monitor and monitor.warning:
        report["resource_warning"] = monitor.warning

    print(json.dumps(report, ensure_ascii=False, indent=2))
    if args.json:
        args.json.parent.mkdir(parents=True, exist_ok=True)
        args.json.write_text(
            json.dumps(report, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
    return 0 if report["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
