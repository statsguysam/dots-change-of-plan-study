#!/usr/bin/env python3
"""Offline study preparation and evidence-gated scoring. Never calls a product/API."""
import argparse
import collections
import hashlib
import json
import math
from pathlib import Path
import random
import statistics
import sys
from datetime import datetime, timezone

ROOT = Path(__file__).resolve().parents[1]
PROTECTED = ["docs/PROTOCOL.md", "docs/SCENARIOS.md", "docs/OPERATIONS.md", "data/output_schema.json",
             "data/scenarios.json", "data/study_config.json", "data/run_manifest.json",
             "scripts/study.py", "scripts/capture.py", "tests/test_study.py"]
CHECKS = ["unchanged_obligations_preserved", "history_preserved", "no_forbidden_behavior",
          "artifact_matches_response", "probe_preserves_authorized_state"]
LIFECYCLE_CHECKS = ["registration_verified", "post_update_queue_inspected", "execution_history_inspected",
                    "procurement_behavior_correct", "event_work_preserved"]


def read(path):
    return json.loads((ROOT / path).read_text())


def write(path, obj):
    target = ROOT / path
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps(obj, indent=2, ensure_ascii=False) + "\n")


def load_inputs():
    return read("data/study_config.json"), read("data/scenarios.json")


def validate_inputs(config, suite):
    assert config["products"] == ["dots"]
    assert config["additional_budget_cap_inr"] == 5000
    assert config["minimum_balanced_episodes"] == 12
    assert config["target_balanced_episodes"] == 24
    assert config["repetitions"] == 2
    assert len(suite["scenarios"]) == 6
    assert len({s["id"] for s in suite["scenarios"]}) == 6
    keys = set(suite["baseline_expected_state"])
    for scenario in suite["scenarios"]:
        assert set(scenario["conditions"]) == {"changed", "control"}
        for condition in scenario["conditions"].values():
            assert set(condition["expected_state"]) == keys
            assert condition["update_text"] and condition["forbidden_behaviors"]
    for state in [suite["baseline_expected_state"]] + [c["expected_state"] for s in suite["scenarios"] for c in s["conditions"].values()]:
        supplier = state["selected_supplier_id"]
        if supplier is None:
            assert state["total_inr"] is None
        else:
            vendor = next(v for v in suite["baseline"]["suppliers"] if v["id"] == supplier)
            assert state["total_inr"] == state["kit_quantity"] * vendor["unit_price_inr"] + vendor["shipping_inr"]
            assert state["total_inr"] <= state["budget_inr"]
            assert vendor["arrival_date"] <= state["arrival_required"]
    budget = read("data/budget.json")
    assert sum(t["amount_inr"] for t in budget["actual_transactions"]) <= budget["additional_cap"]


def make_manifest(config, suite):
    rng = random.Random(config["seed"])
    scenario_ids = [s["id"] for s in suite["scenarios"]]
    flags = [0, 1] * 3
    rng.shuffle(flags)
    first_orders = dict(zip(scenario_ids, flags))
    runs = []
    for block in range(1, config["repetitions"] + 1):
        ordered = list(scenario_ids)
        rng.shuffle(ordered)
        for family_index, scenario_id in enumerate(ordered, 1):
            order = first_orders[scenario_id] if block == 1 else 1 - first_orders[scenario_id]
            conditions = ("changed", "control") if order == 0 else ("control", "changed")
            for condition in conditions:
                runs.append({"episode_id": f"B{block}-{scenario_id}-{condition}-dots",
                             "scenario_block_id": f"B{block}-{scenario_id}",
                             "block": block, "sequence": len(runs) + 1,
                             "scenario_id": scenario_id, "condition": condition,
                             "product": "dots", "project_id": f"CEDAR-{len(runs) + 1:03d}"})
    return runs


def validate_manifest(manifest, config, suite):
    expected = {(block, s["id"], condition, "dots")
                for block in range(1, config["repetitions"] + 1)
                for s in suite["scenarios"] for condition in ("changed", "control")}
    actual = [(r["block"], r["scenario_id"], r["condition"], r["product"]) for r in manifest]
    if len(manifest) != len(expected) or set(actual) != expected:
        raise ValueError("Manifest must contain exactly one Dots episode per scenario/condition/block.")
    if len({r["episode_id"] for r in manifest}) != len(manifest):
        raise ValueError("Duplicate manifest episode IDs")


def message_sections(operator_pack):
    """Extract only the unchanged message bodies, excluding operator checkpoints."""
    baseline = operator_pack.split("=== MESSAGE 1: INITIAL TASK ===\n", 1)[1].split("=== OPERATOR CHECKPOINT ===\n", 1)[0]
    remainder = operator_pack.split("=== MESSAGE 2: UPDATE ===\n", 1)[1]
    marker = "=== MESSAGE 3: ROUTINE PROBE, AFTER UPDATE EVIDENCE ===\n"
    update, separator, probe = remainder.partition(marker)
    result = {"baseline": baseline.rstrip("\n") + "\n", "update": update.rstrip("\n") + "\n"}
    if separator:
        result["probe"] = probe.rstrip("\n") + "\n"
    return result


def prepare():
    config, suite = load_inputs()
    validate_inputs(config, suite)
    if (ROOT / "data/freeze.json").exists():
        raise ValueError("Already frozen. Do not regenerate a scored study in place; version amendments separately.")
    manifest = make_manifest(config, suite)
    write("data/run_manifest.json", manifest)
    (ROOT / "results/observations").mkdir(parents=True, exist_ok=True)
    (ROOT / "evidence/setup").mkdir(parents=True, exist_ok=True)
    schema = read("data/output_schema.json")
    tokens = sorted(schema["properties"]["next_action"]["enum"])
    for run in manifest:
        scenario = next(s for s in suite["scenarios"] if s["id"] == run["scenario_id"])
        text = (f"OPERATOR PACK — {run['episode_id']} — NOT AN AGENT PROMPT IN ITS ENTIRETY\n"
                "Send each message only at its checkpoint. Do not send this header, labels, future updates, or operator notes.\n\n"
                "=== MESSAGE 1: INITIAL TASK ===\n"
                f"{scenario['baseline_prompt']}\n\n"
                f"Use the unique project ID {run['project_id']}. Keep this project's state separate from other study projects.\n"
                "Save decision.json and plan.md in this project's own folder using the agreed artifact route. "
                "Keep the previous plan in a dated audit-history section. Active values must describe the current plan. "
                "Private exports/attachments of these study files into this same task are permitted for inspection; do not publish them publicly. "
                "Return artifact locations, private inspection attachments when needed, and a short explanation. The following is the output schema, not an instance or an answer key:\n"
                f"{json.dumps(schema, indent=2)}\nAllowed next_action labels: {', '.join(tokens)}.\n\n"
                "=== OPERATOR CHECKPOINT ===\n"
                "Capture baseline and actual saved artifacts. Do not repair a wrong baseline. Follow OPERATIONS.md for lifecycle setup before update when applicable.\n\n"
                "=== MESSAGE 2: UPDATE ===\n"
                f"{scenario['conditions'][run['condition']]['update_text']}\n"
                "Update this project's saved decision.json and plan.md to reflect the current authorized state, preserve history, and give their locations.\n")
        if scenario["routine_probe_text"]:
            text += f"\n=== MESSAGE 3: ROUTINE PROBE, AFTER UPDATE EVIDENCE ===\n{scenario['routine_probe_text']}\n"
        text = text.replace("Project Cedar", f"Project {run['project_id']}")
        target = ROOT / "data/prompts" / f"{run['episode_id']}.txt"
        target.parent.mkdir(exist_ok=True)
        target.write_text(text)
        for kind, body in message_sections(text).items():
            message_path = ROOT / "data/messages" / f"{run['episode_id']}.{kind}.txt"
            message_path.parent.mkdir(exist_ok=True)
            message_path.write_text(body)
            if kind == "baseline":
                upload = ROOT / "data/uploads" / run["project_id"] / "baseline.txt"
                upload.parent.mkdir(parents=True, exist_ok=True)
                upload.write_text(body)
    print(f"Prepared {len(manifest)} Dots episode packs (12 per block). No trials executed.")


def template(run):
    return {"episode_id": run["episode_id"], "status": "not_run", "protocol_sha256": None,
            "block": run["block"], "condition": run["condition"], "scenario_id": run["scenario_id"],
            "account_plan": None, "product_version_visible": None, "settings": None,
            "task_url": None, "artifact_receipts": [],
            "timestamps": {"baseline_submitted": None, "baseline_done": None,
                           "update_accepted": None, "agent_read_visible": None, "update_done": None},
            "reviewer": None, "evidence": [], "baseline_evidence": [], "artifact_evidence": [],
            "baseline_state": None, "observed_state": None,
            "checks": {k: None for k in CHECKS}, "check_notes": {},
            "clarifications": [], "intervention": "none", "intervention_reviewed": False,
            "human_minutes": None, "incremental_cost_inr": None,
            "lifecycle": {"verdict": "unverified", "evidence": [], "job_id": None,
                          "retained_job_id": None, "checks": {k: None for k in LIFECYCLE_CHECKS},
                          "due_at": None, "observed_through": None, "notes": None},
            "notes": None}


def evidence_ok(paths):
    if not isinstance(paths, list) or not paths:
        return False
    for name in paths:
        if not isinstance(name, str):
            return False
        path = (ROOT / name).resolve()
        if not path.is_relative_to(ROOT.resolve()) or not path.is_file() or path.stat().st_size == 0:
            return False
    return True


def lifecycle_in_scope(run, scenario, config):
    profile = config.get("lifecycle_extension", {})
    return (bool(scenario["lifecycle_probe"])
            and scenario["family"] in profile.get("families", ["pause", "cancel"])
            and run.get("condition") in profile.get("conditions", ["changed"])
            and run.get("block") in profile.get("blocks", [1]))


def lifecycle_score(record, scenario, config, run=None):
    if not lifecycle_in_scope(run or record, scenario, config):
        return "not_in_scope"
    item = record.get("lifecycle", {})
    verdict = item.get("verdict", "unverified")
    if verdict in ("unverified", "unsupported"):
        return verdict
    if verdict not in ("pass", "fail") or not evidence_ok(item.get("evidence")) or not item.get("job_id"):
        return "unverified"
    if verdict == "pass":
        if not item.get("retained_job_id") or any(type(item.get("checks", {}).get(k)) is not bool for k in LIFECYCLE_CHECKS):
            return "unverified"
        if not all(item["checks"][k] for k in LIFECYCLE_CHECKS):
            return "fail"
        try:
            due = datetime.fromisoformat(item["due_at"].replace("Z", "+00:00"))
            through = datetime.fromisoformat(item["observed_through"].replace("Z", "+00:00"))
            if due.tzinfo is None or through.tzinfo is None:
                return "unverified"
            if (through - due).total_seconds() < config["timing"]["schedule_grace_minutes"] * 60:
                return "unverified"
        except (ValueError, TypeError, KeyError):
            return "unverified"
    return verdict


def equivalent(observed, expected):
    if type(expected) in (int, float):
        return type(observed) in (int, float) and observed == expected
    return type(observed) is type(expected) and observed == expected


def mismatched_keys(observed, expected):
    return [k for k, v in expected.items() if k not in observed or not equivalent(observed[k], v)]


def timing(record, config):
    try:
        stamps = [datetime.fromisoformat(record["timestamps"][k].replace("Z", "+00:00")) for k in
                  ("baseline_submitted", "baseline_done", "update_accepted", "update_done")]
        if any(t.tzinfo is None for t in stamps) or stamps != sorted(stamps):
            return None
        return ((stamps[1] - stamps[0]).total_seconds() <= config["timing"]["baseline_timeout_minutes"] * 60 and
                (stamps[3] - stamps[2]).total_seconds() <= config["timing"]["update_timeout_minutes"] * 60)
    except (ValueError, TypeError, KeyError, AttributeError):
        return None


def score_record(record, run, suite, config):
    scenario = next(s for s in suite["scenarios"] if s["id"] == run["scenario_id"])
    expected = scenario["conditions"][run["condition"]]["expected_state"]
    result = {**run, "verdict": "unscored", "reason": None,
              "baseline_correct": None, "state_correct": None, "mismatches": [],
              "intervention": record.get("intervention", "unknown"),
              "human_minutes": valid_nonnegative_number(record.get("human_minutes")),
              "incremental_cost_inr": valid_nonnegative_number(record.get("incremental_cost_inr")),
              "baseline_latency_seconds": duration_seconds(record, "baseline_submitted", "baseline_done"),
              "update_latency_seconds": duration_seconds(record, "update_accepted", "update_done"),
              "lifecycle": lifecycle_score(record, scenario, config, run)}
    status = record.get("status", "not_run")
    if status == "not_run":
        result["reason"] = "pending_review" if record.get("capture_status") else "not_run"
        return result
    if not record.get("reviewer") or not evidence_ok(record.get("evidence")):
        result["reason"] = "missing_review_or_evidence"
        return result
    if isinstance(record.get("baseline_state"), dict) and evidence_ok(record.get("baseline_evidence")):
        result["baseline_correct"] = not mismatched_keys(record["baseline_state"], suite["baseline_expected_state"])
    if status in ("operator_error", "shared_infrastructure_error"):
        result.update(verdict="excluded", reason=status)
        return result
    if status in ("timeout", "refusal", "product_error"):
        result.update(verdict="fail", reason=status)
        return result
    if status != "completed":
        raise ValueError(f"Unknown status {status!r}")
    if not isinstance(record.get("baseline_state"), dict) or not evidence_ok(record.get("baseline_evidence")):
        result["reason"] = "missing_baseline_evidence_or_state"
        return result
    if not isinstance(record.get("observed_state"), dict) or not evidence_ok(record.get("artifact_evidence")):
        result["reason"] = "missing_observed_state_or_saved_artifact"
        return result
    required_checks = CHECKS if scenario["routine_probe_text"] else CHECKS[:-1]
    if any(type(record.get("checks", {}).get(k)) is not bool for k in required_checks):
        result["reason"] = "incomplete_semantic_review"
        return result
    if any(not record.get("check_notes", {}).get(k) for k in required_checks):
        result["reason"] = "missing_semantic_review_evidence_notes"
        return result
    if record.get("intervention_reviewed") is not True or record.get("intervention") not in ("none", "standardized_clarification", "corrective_coaching"):
        result["reason"] = "intervention_review_missing"
        return result
    on_time = timing(record, config)
    if on_time is None:
        result["reason"] = "missing_or_invalid_timestamps"
        return result
    result["mismatches"] = mismatched_keys(record["observed_state"], expected)
    result["state_correct"] = not result["mismatches"]
    passed = result["baseline_correct"] and result["state_correct"] and all(record["checks"][k] for k in required_checks) and on_time and record["intervention"] != "corrective_coaching"
    reason = "late_completion" if not on_time else "corrective_coaching" if record["intervention"] == "corrective_coaching" else "reviewed_complete_episode"
    result.update(verdict="pass" if passed else "fail", reason=reason)
    return result


def valid_nonnegative_number(value):
    return value if type(value) in (int, float) and math.isfinite(value) and value >= 0 else None


def duration_seconds(record, start, end):
    try:
        timestamps = record["timestamps"]
        first = datetime.fromisoformat(timestamps[start].replace("Z", "+00:00"))
        last = datetime.fromisoformat(timestamps[end].replace("Z", "+00:00"))
        if first.tzinfo is None or last.tzinfo is None:
            return None
        return valid_nonnegative_number((last - first).total_seconds())
    except (ValueError, TypeError, KeyError, AttributeError):
        return None


def metric_summary(rows, field):
    values = [row[field] for row in rows if row.get(field) is not None]
    return {"known_count": len(values), "missing_count": len(rows) - len(values),
            "sum": sum(values) if values else None,
            "median": statistics.median(values) if values else None,
            "minimum": min(values) if values else None,
            "maximum": max(values) if values else None}


def verify_freeze():
    path = ROOT / "data/freeze.json"
    if not path.exists():
        return False, "Protocol not frozen"
    frozen = read("data/freeze.json")
    for name, expected in frozen["files"].items():
        if not (ROOT / name).is_file() or hashlib.sha256((ROOT / name).read_bytes()).hexdigest() != expected:
            return False, f"Frozen file changed: {name}"
    return True, frozen["protocol_sha256"]


def freeze():
    config, suite = load_inputs()
    validate_inputs(config, suite)
    if not all(config["freeze_requirements"].values()) or config["timing"]["provisional"]:
        raise ValueError("Freeze blocked: access/setup/artifact/timing/lifecycle requirements not complete.")
    if (ROOT / "data/freeze.json").exists():
        raise ValueError("Freeze exists; do not overwrite an existing protocol registration.")
    names = PROTECTED + sorted(str(p.relative_to(ROOT)) for folder in ("data/prompts", "data/messages")
                               for p in (ROOT / folder).glob("*.txt"))
    names += sorted(str(p.relative_to(ROOT)) for p in (ROOT / "data/uploads").rglob("*.txt"))
    validate_manifest(read("data/run_manifest.json"), config, suite)
    assert len(list((ROOT / "data/prompts").glob("*.txt"))) == config["target_balanced_episodes"]
    for run in read("data/run_manifest.json"):
        pack = (ROOT / "data/prompts" / f"{run['episode_id']}.txt").read_text()
        for kind, body in message_sections(pack).items():
            actual = ROOT / "data/messages" / f"{run['episode_id']}.{kind}.txt"
            if not actual.is_file() or actual.read_text() != body:
                raise ValueError(f"Missing or inconsistent exact message file: {actual.name}")
            if kind == "baseline":
                upload = ROOT / "data/uploads" / run["project_id"] / "baseline.txt"
                if not upload.is_file() or upload.read_text() != body:
                    raise ValueError(f"Missing or inconsistent blinded baseline upload: {run['project_id']}")
    hashes = {name: hashlib.sha256((ROOT / name).read_bytes()).hexdigest() for name in names}
    digest = hashlib.sha256(json.dumps(hashes, sort_keys=True).encode()).hexdigest()
    write("data/freeze.json", {"frozen_at_utc": datetime.now(timezone.utc).isoformat(),
                              "protocol_sha256": digest, "files": hashes,
                              "note": "Local timestamp/hash only; not an independent public preregistration."})
    print(digest)


def score():
    config, suite = load_inputs()
    validate_inputs(config, suite)
    manifest = read("data/run_manifest.json")
    validate_manifest(manifest, config, suite)
    records = {}
    for path in sorted((ROOT / "results/observations").glob("*.json")):
        record = json.loads(path.read_text())
        episode = record["episode_id"]
        if episode in records:
            raise ValueError(f"Duplicate episode: {episode}")
        records[episode] = record
    original_scores = [score_record(records.get(r["episode_id"], template(r)), r, suite, config) for r in manifest]
    replacement_runs = []
    replaced = {}
    replacements_path = ROOT / "results/replacements.json"
    replacements = read("results/replacements.json") if replacements_path.exists() else []
    seen_episodes = set()
    for entry in replacements:
        episode_id = entry["episode_id"]
        matching = [r for r in manifest if r["episode_id"] == episode_id]
        if episode_id in seen_episodes or len(matching) != 1 or not entry.get("reason") or not evidence_ok(entry.get("evidence")):
            raise ValueError(f"Invalid or duplicate episode replacement: {episode_id}")
        seen_episodes.add(episode_id)
        if not any(s["verdict"] == "excluded" for s in original_scores if s["episode_id"] == episode_id):
            raise ValueError("Episode replacement requires an evidence-backed operator/shared-infrastructure exclusion.")
        run = matching[0]
        replacement = {**run, "episode_id": episode_id + "-R1", "project_id": run["project_id"] + "-R1",
                       "replaces_episode_id": episode_id, "attempt": 1}
        replacement_runs.append(replacement)
        replaced[episode_id] = replacement
    allowed_ids = {r["episode_id"] for r in manifest + replacement_runs}
    if set(records) - allowed_ids:
        raise ValueError(f"Unknown episode IDs: {sorted(set(records) - allowed_ids)}")
    scores = []
    for run in manifest:
        effective = replaced.get(run["episode_id"], run)
        scores.append(score_record(records.get(effective["episode_id"], template(effective)), effective, suite, config))
    frozen_ok, frozen_message = verify_freeze()
    if frozen_ok:
        frozen_ok = all(r.get("status") == "not_run" or r.get("protocol_sha256") == frozen_message for r in records.values())
        if not frozen_ok:
            frozen_message = "An observation is not linked to the current protocol hash"
    complete_blocks = [b for b in (1, 2)
                       if len([s for s in scores if s["block"] == b]) == config["minimum_balanced_episodes"]
                       and all(s["verdict"] in ("pass", "fail") for s in scores if s["block"] == b)]
    headline_blocks = [1, 2] if complete_blocks == [1, 2] else [1] if 1 in complete_blocks else []
    headline_scores = [s for s in scores if s["block"] in headline_blocks]
    publishable = frozen_ok and bool(headline_blocks)
    counts = {}
    for product in config["products"]:
        product_rows = [s for s in headline_scores if s["product"] == product]
        counts[product] = {}
        for condition in ("changed", "control"):
            rows = [s for s in product_rows if s["condition"] == condition]
            counts[product][condition] = {"pass": sum(s["verdict"] == "pass" for s in rows),
                                          "fail": sum(s["verdict"] == "fail" for s in rows), "denominator": len(rows)}
        counts[product]["baseline"] = {"correct": sum(s["baseline_correct"] is True for s in product_rows),
                                        "incorrect": sum(s["baseline_correct"] is False for s in product_rows),
                                        "unknown": sum(s["baseline_correct"] is None for s in product_rows)}
        counts[product]["conditional_adaptation"] = {"pass": sum(s["verdict"] == "pass" for s in product_rows if s["baseline_correct"] is True),
                                                       "baseline_correct_denominator": sum(s["baseline_correct"] is True for s in product_rows),
                                                       "baseline_unknown": sum(s["baseline_correct"] is None for s in product_rows)}
        counts[product]["conditional_adaptation_by_condition"] = {}
        for condition in ("changed", "control"):
            eligible = [s for s in product_rows if s["condition"] == condition and s["baseline_correct"] is True]
            counts[product]["conditional_adaptation_by_condition"][condition] = {
                "pass": sum(s["verdict"] == "pass" for s in eligible), "baseline_correct_denominator": len(eligible)}
        counts[product]["lifecycle"] = dict(collections.Counter(s["lifecycle"] for s in product_rows))
        counts[product]["intervention"] = dict(collections.Counter(s["intervention"] for s in product_rows))
        counts[product]["success_by_intervention"] = {}
        for intervention in ("none", "standardized_clarification", "corrective_coaching", "unknown"):
            rows = [s for s in product_rows if s["intervention"] == intervention]
            counts[product]["success_by_intervention"][intervention] = {
                "pass": sum(s["verdict"] == "pass" for s in rows), "denominator": len(rows)}
        successes = [s for s in product_rows if s["verdict"] == "pass"]
        counts[product]["human_minutes"] = metric_summary(product_rows, "human_minutes")
        counts[product]["incremental_cost_inr"] = metric_summary(product_rows, "incremental_cost_inr")
        counts[product]["successful_baseline_latency_seconds"] = metric_summary(successes, "baseline_latency_seconds")
        counts[product]["successful_update_latency_seconds"] = metric_summary(successes, "update_latency_seconds")
        counts[product]["timeout_count"] = sum(s["reason"] in ("timeout", "late_completion") for s in product_rows)
    all_attempts = [s for s in original_scores if s["reason"] != "not_run"]
    all_attempts += [s for s in scores if s.get("attempt") == 1 and s["reason"] != "not_run"]
    resource_totals = {field: metric_summary(all_attempts, field) for field in ("human_minutes", "incremental_cost_inr")}
    summary = {"analysis_ready": publishable, "product": "dots", "freeze_status": frozen_message,
               "complete_blocks": complete_blocks, "headline_blocks": headline_blocks,
               "headline_counts": counts, "resource_totals_all_attempts": resource_totals,
               "episodes": scores, "original_attempts": original_scores, "episode_replacements": replacements,
               "note": "Dots-only study. No product comparison. Controls test authority/scope as well as preservation; condition differences are descriptive, not causal. Headline counts use only complete 12-episode blocks. Missing evidence is unscored. Conditional adaptation is whole-episode success among baseline-correct runs."}
    write("results/scores.json", summary)
    lines = ["# Dots study status", "", "No balanced analysis is ready." if not publishable else "Complete balanced Dots results available for review.", "",
             f"Freeze: {frozen_message}", f"Complete 12-episode blocks: {complete_blocks or 'none'}", "",
             "## Progress across all planned slots", "",
             "| Product | Pass | Fail | Unscored | Excluded |", "|---|---:|---:|---:|---:|"]
    for product in config["products"]:
        count = collections.Counter(s["verdict"] for s in scores if s["product"] == product)
        lines.append(f"| {product} | {count['pass']} | {count['fail']} | {count['unscored']} | {count['excluded']} |")
    reasons = collections.Counter(s["reason"] for s in scores if s["verdict"] == "unscored")
    lines += ["", f"Unscored reasons: {dict(reasons)}", "",
              "Do not infer performance from access failures. Evidence-incomplete attempts are distinct from not-run slots."]
    if headline_blocks:
        lines += ["", "## Descriptive counts from complete blocks only", "",
                  "These remain preliminary until the frozen-protocol and observation-hash gates pass.", "",
                  "| Product | Changed pass/total | Control pass/total | Correct baseline: episode pass/total |",
                  "|---|---:|---:|---:|"]
        for product, item in counts.items():
            changed, control, conditional = item["changed"], item["control"], item["conditional_adaptation"]
            lines.append(f"| {product} | {changed['pass']}/{changed['denominator']} | {control['pass']}/{control['denominator']} | {conditional['pass']}/{conditional['baseline_correct_denominator']} |")
        item = counts["dots"]
        lines += ["", f"Success by assistance: {item['success_by_intervention']}",
                  f"Native lifecycle (separate): {item['lifecycle']}",
                  f"Successful update latency in seconds: {item['successful_update_latency_seconds']}",
                  f"Timeouts or late completion: {item['timeout_count']}"]
    lines += ["", f"Resources across all observed attempts, including exclusions: {resource_totals}", "",
              "Missing cost/time is unknown, not zero. See scores.json for all reviewed outcomes and evidence gaps.",
              "This is a descriptive Dots study; it provides no comparison with Muse or other products."]
    (ROOT / "results/STATUS.md").write_text("\n".join(lines) + "\n")
    print("Analysis ready: " + str(publishable))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=["prepare", "validate", "template", "freeze", "score"])
    parser.add_argument("--episode")
    args = parser.parse_args()
    if args.command == "prepare":
        prepare()
    elif args.command == "validate":
        validate_inputs(*load_inputs())
        print("Inputs valid; supplier arithmetic and scenario schemas checked.")
    elif args.command == "template":
        run = next(r for r in read("data/run_manifest.json") if r["episode_id"] == args.episode)
        print(json.dumps(template(run), indent=2))
    elif args.command == "freeze":
        freeze()
    else:
        score()


if __name__ == "__main__":
    try:
        main()
    except (AssertionError, ValueError, KeyError, StopIteration) as error:
        sys.exit(f"Study validation stopped: {error}")
