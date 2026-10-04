#!/usr/bin/env python3
"""Capture raw observed UI text without grading or inventing product outcomes.

Example:
  python3 scripts/capture.py --episode B1-S01_budget-changed-dots \
      --phase baseline_done --at 2026-10-04T12:30:00Z < observed-ui.txt

Raw files and events.jsonl are append-only. The observation JSON is a mutable
evidence index for later independent review; capturing text does not score it.
"""

import argparse
from datetime import datetime, timezone
import fcntl
import json
import os
from pathlib import Path
import re
import sys
import tempfile

sys.dont_write_bytecode = True
import study


PHASES = ("baseline_submitted", "baseline_done", "update_accepted", "update_done",
          "probe", "lifecycle", "note")
SINGLE_TIMESTAMPS = frozenset(PHASES[:4])
DEFAULT_ROOT = Path(__file__).resolve().parents[1]


def read_json(path):
    return json.loads(path.read_text())


def timestamp(value=None):
    if value is None:
        return datetime.now(timezone.utc)
    try:
        result = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except (ValueError, TypeError, AttributeError) as error:
        raise ValueError("--at must be an ISO timestamp with an explicit timezone") from error
    if result.tzinfo is None:
        raise ValueError("--at must include Z or an explicit UTC offset; no timezone is inferred")
    return result.astimezone(timezone.utc)


def utc_string(value):
    return value.isoformat(timespec="microseconds").replace("+00:00", "Z")


def resolve_run(root, episode):
    if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_-]{0,180}", episode):
        raise ValueError("Invalid episode ID")
    manifest = read_json(root / "data/run_manifest.json")
    matches = [run for run in manifest if run["episode_id"] == episode]
    if len(matches) == 1:
        return matches[0]
    if episode.endswith("-R1"):
        original_id = episode[:-3]
        originals = [run for run in manifest if run["episode_id"] == original_id]
        replacement_path = root / "results/replacements.json"
        registered = read_json(replacement_path) if replacement_path.exists() else []
        if len(originals) == 1 and any(item.get("episode_id") == original_id for item in registered):
            original = originals[0]
            return {**original, "episode_id": episode,
                    "project_id": original["project_id"] + "-R1",
                    "replaces_episode_id": original_id, "attempt": 1}
    raise ValueError("Episode is not in the manifest or registered replacement list")


def append_reference(record, key, relative_path):
    values = record.setdefault(key, [])
    if not isinstance(values, list):
        raise ValueError(f"Observation {key} must be a list")
    if relative_path not in values:
        values.append(relative_path)


def atomic_json(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary_name = tempfile.mkstemp(prefix=".capture-", suffix=".json", dir=path.parent)
    temporary = Path(temporary_name)
    try:
        with os.fdopen(descriptor, "w") as output:
            output.write(json.dumps(value, indent=2, ensure_ascii=False) + "\n")
            output.flush()
            os.fsync(output.fileno())
        os.replace(temporary, path)
    finally:
        if temporary.exists():
            temporary.unlink()


def capture(root, episode, phase, raw_text, at=None):
    """Store exactly supplied text; do not infer artifact validity or task status."""
    root = Path(root).resolve()
    if phase not in PHASES:
        raise ValueError("Unsupported capture phase")
    if not isinstance(raw_text, str) or not raw_text.strip():
        raise ValueError("No nonempty observed text was supplied on stdin")
    run = resolve_run(root, episode)
    host_time = timestamp()
    event_time = timestamp(at) if at is not None else host_time
    event_at = utc_string(event_time)
    result_directory = root / "results"
    result_directory.mkdir(parents=True, exist_ok=True)
    with (result_directory / ".capture.lock").open("a") as lock:
        fcntl.flock(lock.fileno(), fcntl.LOCK_EX)
        observation_path = result_directory / "observations" / f"{episode}.json"
        record = read_json(observation_path) if observation_path.exists() else study.template(run)
        if record.get("episode_id") != episode:
            raise ValueError("Existing observation belongs to a different episode")
        stamps = record.setdefault("timestamps", {})
        if not isinstance(stamps, dict):
            raise ValueError("Observation timestamps must be an object")
        if phase in SINGLE_TIMESTAMPS and stamps.get(phase) is not None:
            raise ValueError(f"{phase} is already recorded; use a new note to document a correction without overwriting")
        for key in ("evidence", "baseline_evidence", "artifact_evidence"):
            if not isinstance(record.get(key, []), list):
                raise ValueError(f"Observation {key} must be a list")
        if phase == "lifecycle":
            lifecycle = record.setdefault("lifecycle", {})
            if not isinstance(lifecycle, dict) or not isinstance(lifecycle.get("evidence", []), list):
                raise ValueError("Observation lifecycle evidence must be a list")

        evidence_directory = root / "evidence" / episode
        evidence_directory.mkdir(parents=True, exist_ok=True)
        events_path = evidence_directory / "events.jsonl"
        previous_events = []
        if events_path.exists():
            previous_events = [json.loads(line) for line in events_path.read_text().splitlines() if line.strip()]
        if phase != "note" and any(item.get("phase") == phase and item.get("event_at_utc") == event_at for item in previous_events):
            raise ValueError("This phase and timestamp are already captured; raw events are never overwritten")
        basename = event_time.strftime("%Y%m%dT%H%M%S%fZ") + "_" + phase
        raw_path = evidence_directory / f"{basename}.txt"
        if phase == "note":
            number = 1
            while raw_path.exists():
                number += 1
                raw_path = evidence_directory / f"{basename}_{number}.txt"
        elif raw_path.exists():
            raise ValueError("Raw evidence filename already exists; refusing to overwrite")
        relative_raw = str(raw_path.relative_to(root))
        event = {"episode_id": episode, "phase": phase,
                 "event_at_utc": event_at, "captured_at_host_utc": utc_string(host_time),
                 "timestamp_source": "explicit_observed_time" if at is not None else "host_capture_time",
                 "provided_at": at, "evidence_path": relative_raw,
                 "kind": "raw_observation_ungraded"}
        with raw_path.open("x") as output:
            output.write(raw_text)
            output.flush()
            os.fsync(output.fileno())
        with events_path.open("a") as output:
            output.write(json.dumps(event, ensure_ascii=False) + "\n")
            output.flush()
            os.fsync(output.fileno())

        append_reference(record, "evidence", relative_raw)
        if phase == "baseline_done":
            append_reference(record, "baseline_evidence", relative_raw)
        elif phase == "update_done":
            append_reference(record, "artifact_evidence", relative_raw)
        elif phase == "lifecycle":
            append_reference(record["lifecycle"], "evidence", relative_raw)
        if phase in SINGLE_TIMESTAMPS:
            stamps[phase] = event_at
        record["capture_status"] = "raw_evidence_recorded_requires_independent_grading"
        freeze_path = root / "data/freeze.json"
        if record.get("protocol_sha256") is None and freeze_path.exists():
            record["protocol_sha256"] = read_json(freeze_path).get("protocol_sha256")
        atomic_json(observation_path, record)
        return {**event, "observation_path": str(observation_path.relative_to(root)),
                "events_path": str(events_path.relative_to(root)),
                "notice": "Raw text captured. States, semantic checks, and verdict remain for independent review."}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--episode", required=True)
    parser.add_argument("--phase", required=True, choices=PHASES)
    parser.add_argument("--at", help="Exact observed ISO timestamp including timezone; omit to record host capture time")
    parser.add_argument("--root", type=Path, default=DEFAULT_ROOT, help="Study root; useful for isolated testing")
    args = parser.parse_args()
    result = capture(args.root, args.episode, args.phase, sys.stdin.read(), args.at)
    print(json.dumps(result, indent=2, ensure_ascii=False))


if __name__ == "__main__":
    try:
        main()
    except (ValueError, KeyError, OSError, json.JSONDecodeError) as error:
        sys.exit(f"Capture stopped: {error}")
