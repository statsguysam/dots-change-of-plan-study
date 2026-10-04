#!/usr/bin/env python3
"""Preserve one explicitly selected local native-event Markdown download.

Offline evidence collection only: no UI, network, scheduling or grading. Source
bytes remain untouched. The episode-start freshness guard permits documenting
unexpectedly early execution; file mtime never proves scheduler execution time.
"""

import argparse
import fcntl
import json
import os
from pathlib import Path
import re
import sys

sys.dont_write_bytecode = True
import capture
from collect_downloads import source_snapshot


DEFAULT_ROOT = Path(__file__).resolve().parents[1]


def collect(root, episode, source):
    root = Path(root).resolve()
    run = capture.resolve_run(root, episode)
    if Path(source).suffix.lower() != ".md":
        raise ValueError("Provide the exact observed Markdown (.md) download path")
    result_directory = root / "results"
    result_directory.mkdir(parents=True, exist_ok=True)
    with (result_directory / ".capture.lock").open("a") as lock:
        fcntl.flock(lock.fileno(), fcntl.LOCK_EX)
        observation_path = result_directory / "observations" / f"{episode}.json"
        if not observation_path.is_file():
            raise ValueError("Capture the episode baseline before collecting native output")
        record = capture.read_json(observation_path)
        if record.get("episode_id") != episode:
            raise ValueError("Existing observation belongs to another episode")
        start = record.get("timestamps", {}).get("baseline_submitted")
        if not start:
            raise ValueError("A recorded baseline_submitted timestamp is required")
        for key in ("evidence", "artifact_receipts"):
            if not isinstance(record.get(key, []), list):
                raise ValueError(f"Observation {key} must be a list")
        lifecycle = record.get("lifecycle")
        if not isinstance(lifecycle, dict) or not isinstance(lifecycle.get("evidence", []), list):
            raise ValueError("Observation lifecycle evidence must be a list")
        now = capture.timestamp()
        earliest = capture.timestamp(start)
        if earliest > now:
            raise ValueError("Recorded episode start is in the future")
        content, metadata = source_snapshot(source, earliest, now)
        text = content.decode("utf-8-sig")
        if not re.search(r"(?<![A-Za-z0-9_-])" + re.escape(run["project_id"]) + r"(?![A-Za-z0-9_-])", text):
            raise ValueError("Downloaded artifact lacks the exact manifest project ID")
        prior = {r.get("resolved_source_path") for r in record.get("artifact_receipts", [])}
        if metadata["resolved_source_path"] in prior:
            raise ValueError("This source path was already collected; inspect the actual new download")
        directory = root / "evidence" / episode
        paths = {
            "artifact": directory / "native-event-output.download.md",
            "provenance": directory / "native-event-output.provenance.json",
        }
        if any(path.exists() for path in paths.values()):
            raise ValueError("Native output evidence already exists; refusing to overwrite")
        relative = {kind: str(path.relative_to(root)) for kind, path in paths.items()}
        provenance = {
            "episode_id": episode, "project_id": run["project_id"],
            "kind": "actual_native_event_download_ungraded",
            "captured_at_host_utc": capture.utc_string(now),
            "source": "Exact local attachment path explicitly selected by operator after observed native-event output download",
            "freshness_anchor": {"kind": "baseline_submitted", "at_utc": capture.utc_string(earliest)},
            "artifact": {**metadata, "evidence_path": relative["artifact"]},
            "contains_exact_project_id": True,
            "limitations": "Copied bytes and hashes bind this evidence to the selected local download, not an unexposed cloud original. File mtime is a stale-file guard, not execution time. This does not verify content correctness, job identity, actual triggering, retained-event success, or absence of procurement execution. Reviewers must inspect native queue/history and actual artifact contents separately.",
        }
        directory.mkdir(parents=True, exist_ok=True)
        payloads = {"artifact": content,
                    "provenance": (json.dumps(provenance, indent=2, ensure_ascii=False) + "\n").encode()}
        for kind, payload in payloads.items():
            with paths[kind].open("xb") as output:
                output.write(payload)
                output.flush()
                os.fsync(output.fileno())
        event = {"episode_id": episode, "phase": "lifecycle",
                 "kind": "actual_native_event_download_ungraded",
                 "captured_at_host_utc": capture.utc_string(now),
                 "evidence_path": relative["artifact"], "provenance_path": relative["provenance"]}
        with (directory / "events.jsonl").open("a") as output:
            output.write(json.dumps(event) + "\n")
            output.flush()
            os.fsync(output.fileno())
        for path in relative.values():
            capture.append_reference(record, "evidence", path)
            capture.append_reference(lifecycle, "evidence", path)
        record.setdefault("artifact_receipts", []).append({
            **metadata, "phase": "native_event_output", "artifact_kind": "native_event_markdown",
            "evidence_path": relative["artifact"], "provenance_evidence": relative["provenance"],
            "inspection_kind": "copied operator-selected native-event attachment download",
            "byte_identical_to_selected_download": True, "cloud_original_hash_verified": False})
        record["native_capture_status"] = "actual_download_recorded_requires_independent_review"
        capture.atomic_json(observation_path, record)
        return {**event, "notice": "Actual selected bytes preserved; original source retained. No states, checks, timestamps of execution, or verdicts assigned."}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--episode", required=True)
    parser.add_argument("--source", type=Path, required=True)
    parser.add_argument("--root", type=Path, default=DEFAULT_ROOT)
    args = parser.parse_args()
    print(json.dumps(collect(args.root, args.episode, args.source), indent=2))


if __name__ == "__main__":
    try:
        main()
    except (ValueError, KeyError, OSError, UnicodeError) as error:
        sys.exit(f"Native output collection stopped: {error}")
