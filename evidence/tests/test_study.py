"""Regression checks for study fairness and evidence gates; never call products."""

import collections
import contextlib
import copy
from datetime import datetime, timedelta, timezone
import importlib.util
import io
import json
from pathlib import Path
import tempfile
import unittest
from unittest import mock


PROJECT_ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location("study_under_test", PROJECT_ROOT / "scripts/study.py")
study = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(study)

SEMANTIC_CHECKS = [
    "unchanged_obligations_preserved",
    "history_preserved",
    "no_forbidden_behavior",
    "artifact_matches_response",
    "probe_preserves_authorized_state",
]
LIFECYCLE_CHECKS = [
    "registration_verified",
    "post_update_queue_inspected",
    "execution_history_inspected",
    "procurement_behavior_correct",
    "event_work_preserved",
]


def utc(minutes):
    return (datetime(2026, 10, 4, tzinfo=timezone.utc) + timedelta(minutes=minutes)).isoformat()


class StudyTestCase(unittest.TestCase):
    def setUp(self):
        self.config = json.loads((PROJECT_ROOT / "data/study_config.json").read_text())
        self.suite = json.loads((PROJECT_ROOT / "data/scenarios.json").read_text())
        temporary = tempfile.TemporaryDirectory(prefix="dots-change-tests-")
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        patcher = mock.patch.object(study, "ROOT", self.root)
        patcher.start()
        self.addCleanup(patcher.stop)
        (self.root / "evidence").mkdir()
        self.evidence = "evidence/reviewed-trace.txt"
        (self.root / self.evidence).write_text("Synthetic unit-test evidence, not a product observation.\n")
        self.manifest = study.make_manifest(self.config, self.suite)

    def scenario(self, *, lifecycle=False, null_selection=False):
        return next(
            item for item in self.suite["scenarios"]
            if bool(item["lifecycle_probe"]) == lifecycle
            and (not null_selection or item["conditions"]["changed"]["expected_state"]["selected_supplier_id"] is None)
        )

    def completed(self, scenario=None, condition="changed"):
        scenario = scenario or self.scenario()
        run = next(
            item for item in self.manifest
            if item["scenario_id"] == scenario["id"]
            and item["condition"] == condition
            and item["block"] == 1 and item["product"] == "dots"
        )
        record = study.template(run)
        record.update({
            "status": "completed",
            "reviewer": "unit-test-reviewer",
            "evidence": [self.evidence],
            "baseline_evidence": [self.evidence],
            "artifact_evidence": [self.evidence],
            "baseline_state": copy.deepcopy(self.suite["baseline_expected_state"]),
            "observed_state": copy.deepcopy(scenario["conditions"][condition]["expected_state"]),
            "checks": {key: True for key in SEMANTIC_CHECKS},
            "check_notes": {key: "Reviewed against the frozen fixture and trace." for key in SEMANTIC_CHECKS},
            "intervention": "none",
            "intervention_reviewed": True,
            "timestamps": {
                "baseline_submitted": utc(0),
                "baseline_done": utc(2),
                "update_accepted": utc(3),
                "agent_read_visible": None,
                "update_done": utc(4),
            },
        })
        return run, record

    def scored(self, run, record):
        return study.score_record(record, run, self.suite, self.config)

    def verified_lifecycle(self):
        return {
            "verdict": "pass",
            "evidence": [self.evidence],
            "job_id": "synthetic-procurement-job",
            "retained_job_id": "synthetic-event-job",
            "due_at": utc(20),
            "observed_through": utc(20 + self.config["timing"]["schedule_grace_minutes"]),
            "checks": {key: True for key in LIFECYCLE_CHECKS},
            "notes": "Queue state, procurement execution history, and retained event execution inspected.",
        }


class ManifestTests(StudyTestCase):
    def test_manifest_is_deterministic_and_contains_two_balanced_blocks(self):
        self.assertEqual(self.manifest, study.make_manifest(self.config, self.suite))
        self.assertEqual(len(self.manifest), 24)
        self.assertEqual(len({item["episode_id"] for item in self.manifest}), 24)
        expected_cells = {
            (scenario["id"], condition, product)
            for scenario in self.suite["scenarios"]
            for condition in ("changed", "control")
            for product in ("dots",)
        }
        for block in (1, 2):
            with self.subTest(block=block):
                rows = [item for item in self.manifest if item["block"] == block]
                self.assertEqual(len(rows), 12)
                self.assertEqual({(r["scenario_id"], r["condition"], r["product"]) for r in rows}, expected_cells)
                self.assertEqual(collections.Counter(r["product"] for r in rows), {"dots": 12})

    def test_scenario_conditions_are_balanced_and_reverse_order_in_second_block(self):
        orders = {}
        first_counts = {1: collections.Counter(), 2: collections.Counter()}
        for index in range(0, len(self.manifest), 2):
            first, second = self.manifest[index:index + 2]
            self.assertEqual(first["scenario_block_id"], second["scenario_block_id"])
            self.assertNotEqual(first["project_id"], second["project_id"])
            self.assertEqual({first["condition"], second["condition"]}, {"changed", "control"})
            key = first["scenario_id"]
            orders[first["block"], key] = [first["condition"], second["condition"]]
            first_counts[first["block"]][first["condition"]] += 1
        for key in {key for block, key in orders}:
            self.assertEqual(orders[1, key], list(reversed(orders[2, key])))
        self.assertEqual(first_counts[1], {"changed": 3, "control": 3})
        self.assertEqual(first_counts[2], {"changed": 3, "control": 3})


class PrimaryScoringTests(StudyTestCase):
    def test_missing_observation_is_unscored_not_failure(self):
        run = self.manifest[0]
        result = self.scored(run, study.template(run))
        self.assertEqual(result["verdict"], "unscored")
        self.assertIsNone(result["baseline_correct"])

    def test_captured_but_ungraded_observation_is_pending_review(self):
        run = self.manifest[0]
        record = study.template(run)
        self.assertEqual(self.scored(run, record)["reason"], "not_run")
        record["capture_status"] = "raw_evidence_recorded_requires_independent_grading"
        record["evidence"] = [self.evidence]
        result = self.scored(run, record)
        self.assertEqual(result["verdict"], "unscored")
        self.assertEqual(result["reason"], "pending_review")
        self.assertIsNone(result["baseline_correct"])
        self.assertIsNone(result["state_correct"])

    def test_every_correct_scenario_and_control_passes_with_reviewed_evidence(self):
        for scenario in self.suite["scenarios"]:
            for condition in ("changed", "control"):
                with self.subTest(scenario=scenario["id"], condition=condition):
                    run, record = self.completed(scenario, condition)
                    result = self.scored(run, record)
                    self.assertEqual(result["verdict"], "pass", result)
                    self.assertTrue(result["baseline_correct"])
                    self.assertTrue(result["state_correct"])

    def test_missing_evidence_is_unscored(self):
        run, record = self.completed()
        record["artifact_evidence"] = []
        self.assertEqual(self.scored(run, record)["verdict"], "unscored")

    def test_missing_required_null_field_is_a_failed_decision(self):
        run, record = self.completed(self.scenario(null_selection=True))
        self.assertIsNone(record["observed_state"]["selected_supplier_id"])
        del record["observed_state"]["selected_supplier_id"]
        result = self.scored(run, record)
        self.assertEqual(result["verdict"], "fail")
        self.assertIn("selected_supplier_id", result["mismatches"])

    def test_numeric_equivalence_does_not_accept_boolean_as_zero(self):
        run, record = self.completed(condition="control")
        record["observed_state"]["total_inr"] = float(record["observed_state"]["total_inr"])
        record["baseline_state"]["budget_inr"] = float(record["baseline_state"]["budget_inr"])
        self.assertEqual(self.scored(run, record)["verdict"], "pass")
        record["observed_state"]["remote_digital_packets"] = False
        result = self.scored(run, record)
        self.assertEqual(result["verdict"], "fail")
        self.assertIn("remote_digital_packets", result["mismatches"])

    def test_each_missing_required_timestamp_is_unscored(self):
        for field in ("baseline_submitted", "baseline_done", "update_accepted", "update_done"):
            with self.subTest(field=field):
                run, record = self.completed()
                record["timestamps"][field] = None
                self.assertEqual(self.scored(run, record)["verdict"], "unscored")

    def test_late_update_is_failure_even_when_the_decision_is_correct(self):
        run, record = self.completed()
        record["timestamps"]["update_done"] = utc(4 + self.config["timing"]["update_timeout_minutes"])
        self.assertEqual(self.scored(run, record)["verdict"], "fail")

    def test_late_baseline_is_failure_even_when_followup_is_timely(self):
        run, record = self.completed()
        late = self.config["timing"]["baseline_timeout_minutes"] + 1
        record["timestamps"].update(baseline_done=utc(late), update_accepted=utc(late + 1), update_done=utc(late + 2))
        self.assertEqual(self.scored(run, record)["verdict"], "fail")

    def test_corrective_coaching_cannot_turn_an_episode_into_a_primary_pass(self):
        run, record = self.completed()
        record["intervention"] = "corrective_coaching"
        self.assertEqual(self.scored(run, record)["verdict"], "fail")

    def test_unreviewed_intervention_status_is_unscored(self):
        run, record = self.completed()
        record["intervention_reviewed"] = False
        self.assertEqual(self.scored(run, record)["verdict"], "unscored")

    def test_standardized_clarification_can_complete_with_assistance_recorded(self):
        run, record = self.completed()
        record["intervention"] = "standardized_clarification"
        record["clarifications"] = [{"question": "Confirm the currency.", "answer": "INR, as specified in the fixture."}]
        self.assertEqual(self.scored(run, record)["verdict"], "pass")

    def test_postupdate_timeout_keeps_correct_baseline_in_adaptation_denominator(self):
        run, record = self.completed()
        record["status"] = "timeout"
        record["timestamps"]["update_done"] = None
        record["observed_state"] = None
        record["artifact_evidence"] = []
        result = self.scored(run, record)
        self.assertEqual(result["verdict"], "fail")
        self.assertTrue(result["baseline_correct"])

    def test_correct_update_does_not_erase_a_wrong_baseline(self):
        run, record = self.completed()
        record["baseline_state"]["kit_quantity"] = 39
        result = self.scored(run, record)
        self.assertEqual(result["verdict"], "fail")
        self.assertFalse(result["baseline_correct"])

    def test_control_probe_must_preserve_active_procurement(self):
        scenario = self.scenario(lifecycle=True)
        run, record = self.completed(scenario, "control")
        self.assertEqual(record["observed_state"]["procurement_status"], "active")
        self.assertEqual(self.scored(run, record)["verdict"], "pass")
        record["checks"]["probe_preserves_authorized_state"] = False
        self.assertEqual(self.scored(run, record)["verdict"], "fail")


class LifecycleEvidenceTests(StudyTestCase):
    def test_only_changed_pause_and_cancel_in_first_block_are_in_native_scope(self):
        in_scope = []
        for run in self.manifest:
            scenario = next(item for item in self.suite["scenarios"] if item["id"] == run["scenario_id"])
            expected = scenario["family"] in ("pause", "cancel") and run["condition"] == "changed" and run["block"] == 1
            self.assertEqual(study.lifecycle_in_scope(run, scenario, self.config), expected)
            if expected:
                in_scope.append(run)
            else:
                record = study.template(run)
                record["lifecycle"] = self.verified_lifecycle()
                self.assertEqual(study.lifecycle_score(record, scenario, self.config, run), "not_in_scope")
        self.assertEqual(len(in_scope), 2)

    def test_lifecycle_pass_requires_native_queue_and_retained_job_checks(self):
        scenario = self.scenario(lifecycle=True)
        run, record = self.completed(scenario)
        record["lifecycle"] = self.verified_lifecycle()
        self.assertEqual(study.lifecycle_score(record, scenario, self.config), "pass")
        for field in ("post_update_queue_inspected", "execution_history_inspected", "event_work_preserved"):
            with self.subTest(missing_check=field):
                incomplete = copy.deepcopy(record)
                del incomplete["lifecycle"]["checks"][field]
                self.assertEqual(study.lifecycle_score(incomplete, scenario, self.config), "unverified")

    def test_acknowledgment_and_elapsed_time_cannot_prove_native_cancellation(self):
        scenario = self.scenario(lifecycle=True)
        run, record = self.completed(scenario)
        record["lifecycle"] = self.verified_lifecycle()
        record["lifecycle"]["checks"] = {}
        self.assertEqual(study.lifecycle_score(record, scenario, self.config), "unverified")

    def test_both_native_job_identifiers_are_required(self):
        scenario = self.scenario(lifecycle=True)
        run, record = self.completed(scenario)
        for field in ("job_id", "retained_job_id"):
            with self.subTest(field=field):
                record["lifecycle"] = self.verified_lifecycle()
                record["lifecycle"][field] = None
                self.assertEqual(study.lifecycle_score(record, scenario, self.config), "unverified")

    def test_short_observation_window_remains_unverified(self):
        scenario = self.scenario(lifecycle=True)
        run, record = self.completed(scenario)
        record["lifecycle"] = self.verified_lifecycle()
        record["lifecycle"]["observed_through"] = utc(20 + self.config["timing"]["schedule_grace_minutes"] - 1)
        self.assertEqual(study.lifecycle_score(record, scenario, self.config), "unverified")

    def test_unsupported_lifecycle_does_not_become_a_chat_based_pass(self):
        scenario = self.scenario(lifecycle=True)
        run, record = self.completed(scenario)
        record["lifecycle"]["verdict"] = "unsupported"
        result = self.scored(run, record)
        self.assertEqual(result["verdict"], "pass")
        self.assertEqual(result["lifecycle"], "unsupported")


class ScoreOrchestrationTests(StudyTestCase):
    """All generated observations and reports stay in the temporary ROOT."""

    TEST_HASH = "synthetic-test-protocol-hash"

    def setUp(self):
        super().setUp()
        self.save_json("data/study_config.json", self.config)
        self.save_json("data/scenarios.json", self.suite)
        self.save_json("data/run_manifest.json", self.manifest)
        self.save_json("data/budget.json", {
            "additional_cap": 5000,
            "actual_transactions": [],
        })

    def save_json(self, name, value):
        path = self.root / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(value))

    def record_for_run(self, run):
        scenario = next(item for item in self.suite["scenarios"] if item["id"] == run["scenario_id"])
        _, record = self.completed(scenario, run["condition"])
        record["episode_id"] = run["episode_id"]
        record["protocol_sha256"] = self.TEST_HASH
        return record

    def store_observation(self, record):
        self.save_json(f"results/observations/{record['episode_id']}.json", record)

    def run_score(self):
        with mock.patch.object(study, "verify_freeze", return_value=(True, self.TEST_HASH)):
            with contextlib.redirect_stdout(io.StringIO()):
                study.score()
        return json.loads((self.root / "results/scores.json").read_text())

    def test_partial_second_block_does_not_enter_headline_counts(self):
        first_block = [run for run in self.manifest if run["block"] == 1]
        partial_second = [run for run in self.manifest if run["block"] == 2][:2]
        for run in first_block + partial_second:
            record = self.record_for_run(run)
            if run == partial_second[1]:
                record["baseline_state"]["kit_quantity"] = 39
            self.store_observation(record)
        summary = self.run_score()
        self.assertTrue(summary["analysis_ready"])
        self.assertEqual(summary["complete_blocks"], [1])
        self.assertEqual(summary["headline_blocks"], [1])
        self.assertNotIn("paired_outcomes", summary)
        self.assertEqual(summary["product"], "dots")
        for condition in ("changed", "control"):
            self.assertEqual(summary["headline_counts"]["dots"][condition], {"pass": 6, "fail": 0, "denominator": 6})
        second_observed = [row for row in summary["episodes"] if row["block"] == 2 and row["verdict"] in ("pass", "fail")]
        self.assertEqual(len(second_observed), 2)
        self.assertEqual({row["verdict"] for row in second_observed}, {"pass", "fail"})

    def test_justified_single_episode_replacement_preserves_original_and_other_condition(self):
        first_block = [run for run in self.manifest if run["block"] == 1]
        original_run, other_condition = first_block[:2]
        for run in first_block:
            record = self.record_for_run(run)
            if run == original_run:
                record["status"] = "operator_error"
                record["notes"] = "Operator delivered the wrong update; recorded in the trace."
                record["human_minutes"] = 2
            self.store_observation(record)
        replacement_entry = {
            "episode_id": original_run["episode_id"],
            "reason": "Evidence-backed operator error; replace this episode once.",
            "evidence": [self.evidence],
            "registered_at_utc": utc(30),
        }
        self.save_json("results/replacements.json", [replacement_entry])
        replacement = self.record_for_run(original_run)
        replacement["episode_id"] += "-R1"
        replacement["observed_state"]["kit_quantity"] = 999
        replacement["human_minutes"] = 3
        self.store_observation(replacement)
        summary = self.run_score()
        self.assertTrue(summary["analysis_ready"])
        self.assertEqual(summary["episode_replacements"], [replacement_entry])
        original = next(row for row in summary["original_attempts"] if row["episode_id"] == original_run["episode_id"])
        self.assertEqual(original["verdict"], "excluded")
        effective = next(row for row in summary["episodes"] if row.get("replaces_episode_id") == original_run["episode_id"])
        self.assertEqual(effective["episode_id"], original_run["episode_id"] + "-R1")
        self.assertEqual(effective["verdict"], "fail")
        untouched = next(row for row in summary["episodes"] if row["episode_id"] == other_condition["episode_id"])
        self.assertEqual(untouched["verdict"], "pass")
        self.assertNotIn("replaces_episode_id", untouched)
        self.assertEqual(sum(summary["headline_counts"]["dots"][c]["pass"] for c in ("changed", "control")), 11)
        self.assertEqual(summary["resource_totals_all_attempts"]["human_minutes"]["sum"], 5)
        self.assertEqual(summary["resource_totals_all_attempts"]["human_minutes"]["known_count"], 2)

    def test_product_failure_cannot_authorize_an_episode_replacement(self):
        run = self.manifest[0]
        record = self.record_for_run(run)
        record["status"] = "product_error"
        self.store_observation(record)
        self.save_json("results/replacements.json", [{
            "episode_id": run["episode_id"],
            "reason": "Attempted rerun because the product failed.",
            "evidence": [self.evidence],
        }])
        with self.assertRaisesRegex(ValueError, "operator/shared-infrastructure exclusion"):
            self.run_score()
        self.assertFalse((self.root / "results/scores.json").exists())

    def test_resource_and_latency_summary_keeps_unknowns_and_assistance_separate(self):
        first_block = [run for run in self.manifest if run["block"] == 1]
        for index, run in enumerate(first_block):
            record = self.record_for_run(run)
            if index == 0:
                record["human_minutes"] = 2.5
                record["incremental_cost_inr"] = 0
                record["intervention"] = "standardized_clarification"
            self.store_observation(record)
        summary = self.run_score()
        counts = summary["headline_counts"]["dots"]
        self.assertEqual(counts["human_minutes"]["known_count"], 1)
        self.assertEqual(counts["human_minutes"]["missing_count"], 11)
        self.assertEqual(counts["incremental_cost_inr"]["sum"], 0)
        self.assertEqual(counts["successful_update_latency_seconds"]["median"], 60)
        self.assertEqual(counts["successful_update_latency_seconds"]["known_count"], 12)
        self.assertEqual(counts["success_by_intervention"]["none"], {"pass": 11, "denominator": 11})
        self.assertEqual(counts["success_by_intervention"]["standardized_clarification"], {"pass": 1, "denominator": 1})
        self.assertEqual(counts["baseline"], {"correct": 12, "incorrect": 0, "unknown": 0})

    def test_freeze_refuses_incomplete_access_setup_and_timing_gates(self):
        self.config["freeze_requirements"] = {key: False for key in self.config["freeze_requirements"]}
        self.config["timing"]["provisional"] = True
        self.save_json("data/study_config.json", self.config)
        with self.assertRaisesRegex(ValueError, "Freeze blocked"):
            study.freeze()
        self.assertFalse((self.root / "data/freeze.json").exists())

    def test_prepared_messages_and_blinded_uploads_preserve_exact_instruction_content(self):
        schema = json.loads((PROJECT_ROOT / "data/output_schema.json").read_text())
        self.save_json("data/output_schema.json", schema)
        with contextlib.redirect_stdout(io.StringIO()):
            study.prepare()
        baselines = []
        for run in self.manifest:
            self.assertRegex(run["project_id"], r"^CEDAR-[0-9]{3}$")
            pack = (self.root / "data/prompts" / f"{run['episode_id']}.txt").read_text()
            for kind, exact_body in study.message_sections(pack).items():
                actual = (self.root / "data/messages" / f"{run['episode_id']}.{kind}.txt").read_text()
                self.assertEqual(actual, exact_body)
                self.assertNotIn("=== OPERATOR CHECKPOINT ===", actual)
                self.assertNotIn("OPERATOR PACK", actual)
                self.assertNotIn(run["episode_id"], actual)
            upload = self.root / "data/uploads" / run["project_id"] / "baseline.txt"
            self.assertEqual(upload.read_text(), study.message_sections(pack)["baseline"])
            baselines.append(upload.read_text().replace(run["project_id"], "PROJECT_ID"))
        self.assertEqual(len(set(baselines)), 1, "Only opaque project IDs may differ before the update.")
        self.assertEqual(len(list((self.root / "data/uploads").rglob("baseline.txt"))), 24)
        self.assertEqual(len(list((self.root / "data/messages").glob("*.probe.txt"))), 8)

    def test_freeze_hashes_plain_message_files_and_blinded_uploads(self):
        self.save_json("data/output_schema.json", json.loads((PROJECT_ROOT / "data/output_schema.json").read_text()))
        self.config["freeze_requirements"] = {key: True for key in self.config["freeze_requirements"]}
        self.config["timing"]["provisional"] = False
        self.save_json("data/study_config.json", self.config)
        with contextlib.redirect_stdout(io.StringIO()):
            study.prepare()
        for name in study.PROTECTED:
            path = self.root / name
            if not path.exists():
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_text("Temporary unit-test protected fixture; not a real preregistration.\n")
        with contextlib.redirect_stdout(io.StringIO()):
            study.freeze()
        frozen = json.loads((self.root / "data/freeze.json").read_text())
        message_files = list((self.root / "data/messages").glob("*.txt"))
        upload_files = list((self.root / "data/uploads").rglob("*.txt"))
        for path in message_files + upload_files:
            self.assertIn(str(path.relative_to(self.root)), frozen["files"])
        self.assertTrue(study.verify_freeze()[0])
        upload_files[0].write_text("Changed input after freeze\n")
        self.assertFalse(study.verify_freeze()[0])


if __name__ == "__main__":
    unittest.main()
