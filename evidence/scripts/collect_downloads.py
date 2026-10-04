#!/usr/bin/env python3
"""Append exact operator-selected local attachment downloads to study evidence.

No browser, network, grading, or download discovery. Source files are retained.
Run only after the relevant submitted/update/probe timestamp has been captured.
"""

import argparse
from datetime import datetime, timezone
import fcntl
import hashlib
import json
import os
from pathlib import Path
import re
import stat
import sys

sys.dont_write_bytecode = True
import capture
import study


DEFAULT_ROOT = Path(__file__).resolve().parents[1]
PHASES = ("baseline", "update", "probe")


def source_snapshot(path, earliest, now):
    supplied = Path(path).expanduser()
    if not supplied.is_absolute() or any(c in str(supplied) for c in "*?[]"):
        raise ValueError("Give an exact absolute source path, without globs")
    resolved = supplied.resolve(strict=True)
    if supplied != resolved or supplied.is_symlink():
        raise ValueError("Ambiguous/symlink source path; supply the exact resolved regular file")
    before = resolved.stat()
    if not stat.S_ISREG(before.st_mode):
        raise ValueError("Source must be a regular local file")
    if before.st_mtime < earliest.timestamp():
        raise ValueError(f"Stale source predates the recorded phase start: {resolved}")
    if before.st_mtime > now.timestamp() + 1:
        raise ValueError("Source modification time is in the future; inspect clock/provenance first")
    content = resolved.read_bytes()
    after = resolved.stat()
    identity = lambda s: (s.st_dev, s.st_ino, s.st_size, s.st_mtime_ns, s.st_ctime_ns)
    if identity(before) != identity(after) or len(content) != before.st_size:
        raise ValueError("Source changed while being read; wait for download completion")
    if not content:
        raise ValueError("Empty source file")
    return content, {
        "operator_selected_path": str(supplied), "resolved_source_path": str(resolved),
        "source_mtime_utc": capture.utc_string(datetime.fromtimestamp(before.st_mtime, timezone.utc)),
        "source_mtime_ns": before.st_mtime_ns, "source_size_bytes": before.st_size,
        "sha256": hashlib.sha256(content).hexdigest(),
        "source_device": before.st_dev, "source_inode": before.st_ino,
    }


def phase_start(root, episode, phase, record):
    key = {"baseline": "baseline_submitted", "update": "update_accepted"}.get(phase)
    if key:
        value = record.get("timestamps", {}).get(key)
        if not value:
            raise ValueError(f"Capture {key} before collecting downloads")
        return capture.timestamp(value), key
    event_path = root / "evidence" / episode / "events.jsonl"
    events = [json.loads(line) for line in event_path.read_text().splitlines() if line.strip()] if event_path.exists() else []
    times = [capture.timestamp(e["event_at_utc"]) for e in events
             if e.get("phase") == "probe" and e.get("event_at_utc")]
    if not times:
        raise ValueError("Capture the probe submission before collecting probe downloads")
    return max(times), "latest_recorded_probe_event"


def collect(root, episode, phase, decision, plan):
    root = Path(root).resolve()
    if phase not in PHASES:
        raise ValueError("Unsupported phase")
    run = capture.resolve_run(root, episode)
    result_directory = root / "results"
    result_directory.mkdir(parents=True, exist_ok=True)
    with (result_directory / ".capture.lock").open("a") as lock:
        fcntl.flock(lock.fileno(), fcntl.LOCK_EX)
        observation_path = result_directory / "observations" / f"{episode}.json"
        record = capture.read_json(observation_path) if observation_path.exists() else study.template(run)
        if record.get("episode_id") != episode:
            raise ValueError("Observation belongs to another episode")
        for key in ("evidence", "baseline_evidence", "artifact_evidence", "artifact_receipts"):
            if not isinstance(record.get(key, []), list):
                raise ValueError(f"Observation {key} must be a list")
        now = capture.timestamp()
        earliest, anchor_kind = phase_start(root, episode, phase, record)
        if earliest > now:
            raise ValueError("Recorded phase start is in the future")
        decision_bytes, decision_meta = source_snapshot(decision, earliest, now)
        plan_bytes, plan_meta = source_snapshot(plan, earliest, now)
        if (decision_meta["source_device"], decision_meta["source_inode"]) == (plan_meta["source_device"], plan_meta["source_inode"]):
            raise ValueError("Decision and plan cannot refer to the same local file")
        json.loads(decision_bytes.decode("utf-8-sig"))
        plan_text = plan_bytes.decode("utf-8-sig")
        if not re.search(r"(?<![A-Za-z0-9_-])" + re.escape(run["project_id"]) + r"(?![A-Za-z0-9_-])", plan_text):
            raise ValueError("Plan does not contain the exact manifest project ID; inspect attachment identity")
        evidence_directory = root / "evidence" / episode
        targets = {
            "decision": evidence_directory / f"{phase}-decision.download.json",
            "plan": evidence_directory / f"{phase}-plan.download.md",
            "provenance": evidence_directory / f"{phase}-downloads.provenance.json",
        }
        if any(p.exists() for p in targets.values()):
            raise ValueError("Evidence for this phase already exists; refusing overwrite or ambiguous recollection")
        prior_sources = {item.get("resolved_source_path") for item in record.get("artifact_receipts", []) if item.get("resolved_source_path")}
        if any(meta["resolved_source_path"] in prior_sources for meta in (decision_meta, plan_meta)):
            raise ValueError("A selected source path was already used; preserve originals and choose the newly observed downloads")
        relative = {k: str(p.relative_to(root)) for k, p in targets.items()}
        for meta, kind in ((decision_meta, "decision"), (plan_meta, "plan")):
            meta.update(evidence_path=relative[kind], artifact_kind=kind)
        provenance = {
            "episode_id": episode, "project_id": run["project_id"], "phase": phase,
            "captured_at_host_utc": capture.utc_string(now),
            "freshness_anchor": {"kind": anchor_kind, "at_utc": capture.utc_string(earliest)},
            "source": "Exact local paths explicitly selected by operator after supported UI attachment download",
            "files": [decision_meta, plan_meta], "decision_json_parseable": True,
            "plan_contains_exact_project_id": True,
            "limitations": "Hashes establish equality with selected local download bytes at collection, not independent cloud-original identity. mtime is a stale-file guard, not proof of product generation time. No content correctness, semantic outcome, phase completion time, or verdict is inferred.",
        }
        evidence_directory.mkdir(parents=True, exist_ok=True)
        payloads = {"decision": decision_bytes, "plan": plan_bytes,
                    "provenance": (json.dumps(provenance, indent=2, ensure_ascii=False) + "\n").encode()}
        for kind, payload in payloads.items():
            with targets[kind].open("xb") as output:
                output.write(payload)
                output.flush()
                os.fsync(output.fileno())
        event = {"episode_id": episode, "phase": phase, "kind": "actual_attachment_downloads_ungraded",
                 "captured_at_host_utc": capture.utc_string(now), "provenance_path": relative["provenance"]}
        with (evidence_directory / "events.jsonl").open("a") as output:
            output.write(json.dumps(event) + "\n")
            output.flush()
            os.fsync(output.fileno())
        for path in relative.values():
            capture.append_reference(record, "evidence", path)
            capture.append_reference(record, "baseline_evidence" if phase == "baseline" else "artifact_evidence", path)
        for meta in (decision_meta, plan_meta):
            record.setdefault("artifact_receipts", []).append({**meta, "phase": phase,
                "provenance_evidence": relative["provenance"], "inspection_kind": "copied operator-selected actual local attachment download",
                "byte_identical_to_selected_download": True, "cloud_original_hash_verified": False})
        record["capture_status"] = "raw_evidence_recorded_requires_independent_grading"
        capture.atomic_json(observation_path, record)
        return {**event, "files": relative, "notice": "Copies and provenance saved; source files preserved. No grading performed."}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--episode", required=True)
    parser.add_argument("--phase", required=True, choices=PHASES)
    parser.add_argument("--decision", required=True, type=Path)
    parser.add_argument("--plan", required=True, type=Path)
    parser.add_argument("--root", type=Path, default=DEFAULT_ROOT)
    args = parser.parse_args()
    print(json.dumps(collect(args.root, args.episode, args.phase, args.decision, args.plan), indent=2))


if __name__ == "__main__":
    try:
        main()
    except (ValueError, KeyError, OSError, UnicodeError) as error:
        sys.exit(f"Download collection stopped: {error}")
