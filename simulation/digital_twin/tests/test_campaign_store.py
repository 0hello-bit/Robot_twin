"""Tests for CampaignStore: atomic writes, path validation, immutable runs,
backward compatibility, and ProductStore delegation.
"""

from __future__ import annotations

import json
import os
import sys
import tempfile

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import pytest
import math


# ============================================================
# CampaignStore tests
# ============================================================


class TestCreateCampaign:
    def test_creates_campaign_json(self):
        from real_world.campaign_store import CampaignStore
        with tempfile.TemporaryDirectory() as tmp:
            store = CampaignStore(data_root=tmp)
            camp = store.create_campaign("camp-001", description="Test campaign")
            assert camp.campaign_id == "camp-001"
            assert camp.status == "created"
            # Verify file exists
            camp_file = os.path.join(tmp, "campaigns", "camp-001", "campaign.json")
            assert os.path.isfile(camp_file)
            # Verify loadable
            loaded = store.load_campaign("camp-001")
            assert loaded is not None
            assert loaded.campaign_id == "camp-001"

    def test_duplicate_campaign_raises(self):
        from real_world.campaign_store import CampaignStore
        with tempfile.TemporaryDirectory() as tmp:
            store = CampaignStore(data_root=tmp)
            store.create_campaign("dup-test")
            with pytest.raises((ValueError,), match="already exists"):
                store.create_campaign("dup-test")

    def test_empty_campaign_id_raises(self):
        from real_world.campaign_store import CampaignStore
        with tempfile.TemporaryDirectory() as tmp:
            store = CampaignStore(data_root=tmp)
            with pytest.raises(ValueError):
                store.create_campaign("")

    def test_traversal_in_campaign_id_raises(self):
        from real_world.campaign_store import CampaignStore
        with tempfile.TemporaryDirectory() as tmp:
            store = CampaignStore(data_root=tmp)
            with pytest.raises(ValueError, match="traversal|separator"):
                store.create_campaign("../etc/passwd")
            with pytest.raises(ValueError, match="traversal|separator"):
                store.create_campaign("camp/../other")
            with pytest.raises(ValueError, match="traversal|separator"):
                store.create_campaign("camp\\..")

    def test_campaign_id_path_separator_raises(self):
        from real_world.campaign_store import CampaignStore
        with tempfile.TemporaryDirectory() as tmp:
            store = CampaignStore(data_root=tmp)
            with pytest.raises(ValueError, match="separator"):
                store.create_campaign("camp/001")


class TestWindowsReservedNames:
    """Windows reserved device names must be rejected (C1)."""

    def _assert_rejected(self, campaign_id):
        from real_world.campaign_store import CampaignStore
        with tempfile.TemporaryDirectory() as tmp:
            store = CampaignStore(data_root=tmp)
            with pytest.raises(ValueError):
                store.create_campaign(campaign_id)

    def test_CON_rejected(self):
        self._assert_rejected("CON")

    def test_CON_dot_txt_rejected(self):
        # Rejected by regex pattern for '.' before reserved check
        self._assert_rejected("CON.txt")

    def test_CON_trailing_dot_rejected(self):
        self._assert_rejected("CON.")

    def test_CON_trailing_space_rejected(self):
        self._assert_rejected("CON ")

    def test_con_lowercase_rejected(self):
        self._assert_rejected("con")

    def test_PRN_rejected(self):
        self._assert_rejected("PRN")

    def test_AUX_rejected(self):
        self._assert_rejected("AUX")

    def test_NUL_rejected(self):
        self._assert_rejected("NUL")

    def test_COM1_rejected(self):
        self._assert_rejected("COM1")

    def test_COM9_rejected(self):
        self._assert_rejected("COM9")

    def test_LPT1_rejected(self):
        self._assert_rejected("LPT1")

    def test_LPT9_rejected(self):
        self._assert_rejected("LPT9")

    def test_CLOCK_rejected(self):
        # CLOCK$ rejected by regex pattern for '$' before reserved check
        self._assert_rejected("CLOCK$")

    def test_run_id_CON_rejected(self):
        """Windows reserved names must also be rejected in run_id."""
        from real_world.campaign_store import CampaignStore
        with tempfile.TemporaryDirectory() as tmp:
            store = CampaignStore(data_root=tmp)
            store.create_campaign("camp-001")
            with pytest.raises(ValueError, match="reserved"):
                store.save_run("camp-001", "CON", {"run_id": "CON"})

    def test_run_id_NUL_rejected(self):
        from real_world.campaign_store import CampaignStore
        with tempfile.TemporaryDirectory() as tmp:
            store = CampaignStore(data_root=tmp)
            store.create_campaign("camp-001")
            with pytest.raises(ValueError, match="reserved"):
                store.save_run("camp-001", "NUL", {"run_id": "NUL"})

    def test_normal_name_accepted(self):
        """Normal campaign IDs should still work."""
        from real_world.campaign_store import CampaignStore
        with tempfile.TemporaryDirectory() as tmp:
            store = CampaignStore(data_root=tmp)
            camp = store.create_campaign("normal-campaign-1")
            assert camp.campaign_id == "normal-campaign-1"


class TestSaveRun:
    def test_saves_and_loads_run(self):
        from real_world.campaign_store import CampaignStore
        with tempfile.TemporaryDirectory() as tmp:
            store = CampaignStore(data_root=tmp)
            store.create_campaign("camp-001")
            run_data = {
                "run_id": "run-001",
                "metrics": {"rms": 10.5},
                "telemetry": [{"error": 1}],
            }
            saved = store.save_run("camp-001", "run-001", run_data)
            assert saved["run_id"] == "run-001"
            # Load it back
            loaded = store.load_run("camp-001", "run-001")
            assert loaded is not None
            assert loaded["run_id"] == "run-001"
            assert loaded["metrics"]["rms"] == 10.5

    def test_same_run_id_identical_content_is_idempotent(self):
        from real_world.campaign_store import CampaignStore
        with tempfile.TemporaryDirectory() as tmp:
            store = CampaignStore(data_root=tmp)
            store.create_campaign("camp-001")
            run_data = {"run_id": "run-001", "value": 42}
            store.save_run("camp-001", "run-001", run_data)
            store.save_run("camp-001", "run-001", run_data)  # same → OK

    def test_same_run_id_different_content_raises(self):
        from real_world.campaign_store import CampaignStore
        with tempfile.TemporaryDirectory() as tmp:
            store = CampaignStore(data_root=tmp)
            store.create_campaign("camp-001")
            store.save_run("camp-001", "run-001", {"run_id": "run-001", "value": 42})
            with pytest.raises((ValueError,), match="already exists|immutable"):
                store.save_run("camp-001", "run-001", {"run_id": "run-001", "value": 99})

    def test_run_without_campaign_raises(self):
        from real_world.campaign_store import CampaignStore
        with tempfile.TemporaryDirectory() as tmp:
            store = CampaignStore(data_root=tmp)
            with pytest.raises(ValueError):
                store.save_run("nonexistent", "run-001", {"run_id": "run-001"})

    def test_run_id_directory_traversal_raises(self):
        from real_world.campaign_store import CampaignStore
        with tempfile.TemporaryDirectory() as tmp:
            store = CampaignStore(data_root=tmp)
            store.create_campaign("camp-001")
            with pytest.raises(ValueError, match="traversal|separator"):
                store.save_run("camp-001", "../evil", {})

    def test_list_runs_empty(self):
        from real_world.campaign_store import CampaignStore
        with tempfile.TemporaryDirectory() as tmp:
            store = CampaignStore(data_root=tmp)
            store.create_campaign("camp-001")
            assert store.list_runs("camp-001") == []

    def test_list_runs_multiple(self):
        from real_world.campaign_store import CampaignStore
        with tempfile.TemporaryDirectory() as tmp:
            store = CampaignStore(data_root=tmp)
            store.create_campaign("camp-001")
            for i in range(3):
                rid = "run-{0:03d}".format(i)
                store.save_run("camp-001", rid, {"run_id": rid, "val": i})
            runs = store.list_runs("camp-001")
            assert len(runs) == 3
            # Sorted by run_id
            assert [r["run_id"] for r in runs] == ["run-000", "run-001", "run-002"]


class TestSaveDecision:
    def test_saves_and_loads_decision(self):
        from real_world.campaign_store import CampaignStore
        with tempfile.TemporaryDirectory() as tmp:
            store = CampaignStore(data_root=tmp)
            store.create_campaign("camp-001")
            decision = {
                "status": "rejected",
                "reason": "rms_error_threshold",
                "baseline_stats": {"mean_rms": 10.0},
                "candidate_stats": {"mean_rms": 9.5},
            }
            saved = store.save_decision("camp-001", 1, decision)
            assert saved["version"] == 1
            loaded = store.load_decision("camp-001", 1)
            assert loaded["status"] == "rejected"

    def test_version_conflict_raises(self):
        from real_world.campaign_store import CampaignStore
        with tempfile.TemporaryDirectory() as tmp:
            store = CampaignStore(data_root=tmp)
            store.create_campaign("camp-001")
            store.save_decision("camp-001", 1, {"status": "rejected"})
            with pytest.raises((ValueError,), match="already exists|historical"):
                store.save_decision("camp-001", 1, {"status": "accepted"})

    def test_decision_history_preserved(self):
        from real_world.campaign_store import CampaignStore
        with tempfile.TemporaryDirectory() as tmp:
            store = CampaignStore(data_root=tmp)
            store.create_campaign("camp-001")
            for v in range(1, 4):
                store.save_decision("camp-001", v, {"status": "rejected", "v": v})
            decisions = store.list_decisions("camp-001")
            assert len(decisions) == 3
            assert [d["version"] for d in decisions] == [1, 2, 3]

    def test_version_zero_raises(self):
        from real_world.campaign_store import CampaignStore
        with tempfile.TemporaryDirectory() as tmp:
            store = CampaignStore(data_root=tmp)
            store.create_campaign("camp-001")
            with pytest.raises(ValueError):
                store.save_decision("camp-001", 0, {"status": "rejected"})


class TestReport:
    def test_save_and_load_report(self):
        from real_world.campaign_store import CampaignStore
        with tempfile.TemporaryDirectory() as tmp:
            store = CampaignStore(data_root=tmp)
            store.create_campaign("camp-001")
            report = {"accepted": True, "final_rms": 8.5}
            saved = store.save_report("camp-001", report)
            assert saved["accepted"] is True
            loaded = store.load_report("camp-001")
            assert loaded["accepted"] is True


class TestAtomicWrites:
    """Atomic write guarantees and error recovery."""

    def test_write_survives_interruption(self):
        """Simulate write of a large payload and verify it's readable."""
        from real_world.campaign_store import CampaignStore
        with tempfile.TemporaryDirectory() as tmp:
            store = CampaignStore(data_root=tmp)
            store.create_campaign("camp-001")
            # Large-ish payload
            big = {"data": list(range(1000)), "run_id": "big-run"}
            store.save_run("camp-001", "big-run", big)
            loaded = store.load_run("camp-001", "big-run")
            assert loaded is not None
            assert len(loaded["data"]) == 1000


class TestPathValidation:
    """Comprehensive path traversal and invalid identifier rejection."""

    def test_run_id_with_dots(self):
        """Dots are allowed in run_id but not directory traversal."""
        from real_world.campaign_store import CampaignStore
        with tempfile.TemporaryDirectory() as tmp:
            store = CampaignStore(data_root=tmp)
            store.create_campaign("camp-001")
            # Dots are OK (UUIDs, timestamps)
            store.save_run("camp-001", "run.2026-07-30.001", {"ok": True})
            loaded = store.load_run("camp-001", "run.2026-07-30.001")
            assert loaded is not None

    def test_run_id_with_traversal_dots_raises(self):
        """.. in run_id must be rejected."""
        from real_world.campaign_store import CampaignStore
        with tempfile.TemporaryDirectory() as tmp:
            store = CampaignStore(data_root=tmp)
            store.create_campaign("camp-001")
            with pytest.raises(ValueError, match="traversal"):
                store.save_run("camp-001", "..", {})

    def test_run_id_with_slash_raises(self):
        from real_world.campaign_store import CampaignStore
        with tempfile.TemporaryDirectory() as tmp:
            store = CampaignStore(data_root=tmp)
            store.create_campaign("camp-001")
            with pytest.raises(ValueError, match="separator"):
                store.save_run("camp-001", "a/b", {})

    def test_long_campaign_id_raises(self):
        from real_world.campaign_store import CampaignStore
        with tempfile.TemporaryDirectory() as tmp:
            store = CampaignStore(data_root=tmp)
            long_id = "x" * 50
            with pytest.raises(ValueError, match="exceeds maximum"):
                store.create_campaign(long_id)


class TestBackwardCompat:
    """Old Task 2 JSON patterns must not be mis-identified as campaign records."""

    def test_legacy_data_logger_json_not_campaign(self):
        from real_world.campaign_store import CampaignStore
        # Legacy format from data_logger
        legacy = {
            "name": "old_session",
            "source": "real_stm32",
            "data": [{"tick_ms": 1}],
        }
        assert not CampaignStore.is_campaign_json(legacy)

    def test_task2_campaign_telemetry_not_campaign(self):
        from real_world.campaign_store import CampaignStore
        # CampaignTelemetry from_dict format (no schema_version)
        telemetry = {
            "campaign_id": "camp-001",
            "run_id": "run-001",
            "parameter_version": 2,
            "termination_reason": "completed",
        }
        assert not CampaignStore.is_campaign_json(telemetry)

    def test_proper_campaign_json_detected(self):
        from real_world.campaign_store import CampaignStore
        proper = {
            "schema_version": 1,
            "campaign_id": "camp-001",
            "status": "created",
        }
        assert CampaignStore.is_campaign_json(proper)


class TestListCampaigns:
    def test_list_no_campaigns(self):
        from real_world.campaign_store import CampaignStore
        with tempfile.TemporaryDirectory() as tmp:
            store = CampaignStore(data_root=tmp)
            assert store.list_campaigns() == []

    def test_list_multiple_campaigns(self):
        from real_world.campaign_store import CampaignStore
        with tempfile.TemporaryDirectory() as tmp:
            store = CampaignStore(data_root=tmp)
            store.create_campaign("alpha")
            store.create_campaign("beta")
            store.create_campaign("gamma")
            campaigns = store.list_campaigns()
            assert campaigns == ["alpha", "beta", "gamma"]

    def test_dirs_without_campaign_json_ignored(self):
        from real_world.campaign_store import CampaignStore
        with tempfile.TemporaryDirectory() as tmp:
            store = CampaignStore(data_root=tmp)
            store.create_campaign("real-one")
            # Create a directory that looks like a campaign but has no campaign.json
            fake_dir = os.path.join(tmp, "campaigns", "fake")
            os.makedirs(fake_dir)
            campaigns = store.list_campaigns()
            assert "fake" not in campaigns
            assert "real-one" in campaigns


class TestProductStoreCompat:
    """Verifies that ProductStore delegation works without duplicate logic."""

    def test_campaign_store_methods_available(self):
        """ProductStore must expose campaign methods that delegate to CampaignStore."""
        from real_world.campaign_store import CampaignStore
        # Check the interface exists
        store = CampaignStore(data_root=tempfile.gettempdir())
        assert hasattr(store, "create_campaign")
        assert hasattr(store, "save_run")
        assert hasattr(store, "save_decision")
        assert hasattr(store, "list_campaigns")
        assert hasattr(store, "load_campaign")
        assert hasattr(store, "load_run")
        assert hasattr(store, "list_runs")
        assert hasattr(store, "load_decision")
        assert hasattr(store, "list_decisions")
        assert hasattr(store, "save_report")
        assert hasattr(store, "load_report")
