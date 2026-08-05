"""Atomic, immutable campaign storage for line-following PID optimization.

Data layout under the campaign root:
  data/campaigns/<campaign_id>/
    campaign.json              — campaign metadata
    runs/<run_id>.json         — per-run telemetry and summary (immutable once written)
    candidates/<version>.json  — per-candidate decision history (append-only)
    report.json                — final campaign report

All writes are atomic: content is written to a temporary file in the same
directory, fsynced, then os.replace()d into place. A failed write leaves
the previous state intact.
"""

from __future__ import annotations

import copy
import json
import math
import os
import re
import tempfile
from dataclasses import dataclass, field, asdict
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Sequence


CAMPAIGN_SCHEMA_VERSION = 1
CAMPAIGN_ID_RE = re.compile(r"^[A-Za-z0-9_-]+$")
RUN_ID_RE = re.compile(r"^[A-Za-z0-9_.-]+$")
MAX_ID_LENGTH = 64
MAX_CAMPAIGN_ID_LENGTH = 48


# Windows reserved device names — case-insensitive, also rejected with
# any extension or trailing dot/space (e.g. CON.txt, NUL., "CON ").
_WINDOWS_RESERVED_NAMES = frozenset(
    n.upper() for n in [
        "CON", "PRN", "AUX", "NUL", "CLOCK$",
        "COM1", "COM2", "COM3", "COM4", "COM5", "COM6", "COM7", "COM8", "COM9",
        "LPT1", "LPT2", "LPT3", "LPT4", "LPT5", "LPT6", "LPT7", "LPT8", "LPT9",
    ]
)


def _is_windows_reserved(name: str) -> bool:
    """Check if *name* is a Windows reserved device name or variant.

    Rejects bare names (CON, NUL), dotted extensions (CON.txt, aux.),
    and trailing dot/space (``NUL.``, ``CON ``).  Case-insensitive.
    """
    # Strip trailing dots and spaces (Windows normalizes these away)
    stripped = name.rstrip(". ")
    base = stripped.split(".")[0]  # CON.txt → CON  (also handles "aux.")
    return base.upper() in _WINDOWS_RESERVED_NAMES


class CampaignStoreError(ValueError):
    """Raised on invalid input or storage violations."""


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _safe_identifier(value: str, pattern: re.Pattern, max_length: int, name: str) -> str:
    """Validate and return a safe filesystem identifier."""
    if not isinstance(value, str) or not value:
        raise CampaignStoreError("{0} must be a non-empty string".format(name))
    if len(value) > max_length:
        raise CampaignStoreError("{0} exceeds maximum length {1}".format(name, max_length))
    if ".." in value or "/" in value or "\\" in value:
        raise CampaignStoreError("{0} contains path separator or directory traversal".format(name))
    if not pattern.fullmatch(value):
        raise CampaignStoreError(
            "{0} '{1}' contains invalid characters".format(name, value)
        )
    if _is_windows_reserved(value):
        raise CampaignStoreError(
            "{0} '{1}' is a Windows reserved device name".format(name, value)
        )
    return value


def _validate_version(version: Any) -> int:
    """Validate candidate version is a positive integer."""
    if isinstance(version, bool) or not isinstance(version, int):
        raise CampaignStoreError("version must be a positive integer")
    if version <= 0 or version > 0xFFFFFFFF:
        raise CampaignStoreError("version out of range")
    return version


# ============================================================
# Data models
# ============================================================


@dataclass
class Campaign:
    """Campaign metadata."""
    campaign_id: str = ""
    schema_version: int = CAMPAIGN_SCHEMA_VERSION
    created_at: str = ""
    updated_at: str = ""
    description: str = ""
    track_id: str = ""
    firmware_version: str = ""
    baseline_params: Dict[str, Any] = field(default_factory=dict)
    status: str = "created"  # created | baseline | evaluating | complete

    def to_dict(self) -> dict:
        return {
            "schema_version": self.schema_version,
            "campaign_id": self.campaign_id,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
            "description": self.description,
            "track_id": self.track_id,
            "firmware_version": self.firmware_version,
            "baseline_params": self.baseline_params,
            "status": self.status,
        }

    @staticmethod
    def from_dict(data: dict) -> "Campaign":
        return Campaign(
            campaign_id=data.get("campaign_id", ""),
            schema_version=data.get("schema_version", CAMPAIGN_SCHEMA_VERSION),
            created_at=data.get("created_at", ""),
            updated_at=data.get("updated_at", ""),
            description=data.get("description", ""),
            track_id=data.get("track_id", ""),
            firmware_version=data.get("firmware_version", ""),
            baseline_params=data.get("baseline_params", {}),
            status=data.get("status", "created"),
        )


def _read_json(path: str, default: Any = None) -> Any:
    """Read JSON file, returning default on missing file or parse error."""
    if not os.path.isfile(path):
        return copy.deepcopy(default)
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except (json.JSONDecodeError, OSError):
        return copy.deepcopy(default)


def _atomic_write_json(path: str, payload: Any) -> None:
    """Atomically write JSON payload to path using temp file + os.replace()."""
    directory = os.path.dirname(os.path.abspath(path))
    os.makedirs(directory, exist_ok=True)
    fd, temp_path = tempfile.mkstemp(
        prefix=".campaign_", suffix=".json", dir=directory,
    )
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump(payload, f, ensure_ascii=False, indent=2)
            f.write("\n")
            f.flush()
            os.fsync(f.fileno())
        os.replace(temp_path, path)
    except BaseException:
        # On any error, clean up the temp file and re-raise
        if os.path.exists(temp_path):
            os.unlink(temp_path)
        raise


class CampaignStore:
    """Atomic, immutable campaign storage.

    Root directory: data/campaigns/<campaign_id>/
    All paths are validated against directory traversal.
    """

    def __init__(self, data_root: str = "data"):
        self._data_root = os.path.abspath(data_root)

    # ----------------------------------------------------------
    # Path helpers
    # ----------------------------------------------------------

    def _campaign_dir(self, campaign_id: str) -> str:
        return os.path.join(self._data_root, "campaigns", campaign_id)

    def _campaign_file(self, campaign_id: str) -> str:
        return os.path.join(self._campaign_dir(campaign_id), "campaign.json")

    def _run_dir(self, campaign_id: str) -> str:
        return os.path.join(self._campaign_dir(campaign_id), "runs")

    def _run_file(self, campaign_id: str, run_id: str) -> str:
        return os.path.join(self._run_dir(campaign_id), "{0}.json".format(run_id))

    def _candidate_dir(self, campaign_id: str) -> str:
        return os.path.join(self._campaign_dir(campaign_id), "candidates")

    def _candidate_file(self, campaign_id: str, version: int) -> str:
        return os.path.join(
            self._candidate_dir(campaign_id), "{0}.json".format(version)
        )

    def _report_file(self, campaign_id: str) -> str:
        return os.path.join(self._campaign_dir(campaign_id), "report.json")

    # ----------------------------------------------------------
    # Campaign CRUD
    # ----------------------------------------------------------

    def create_campaign(
        self,
        campaign_id: str,
        description: str = "",
        track_id: str = "",
        firmware_version: str = "",
        baseline_params: Optional[Dict[str, Any]] = None,
    ) -> Campaign:
        """Create a new campaign and write campaign.json. Raises if exists."""
        _safe_identifier(campaign_id, CAMPAIGN_ID_RE, MAX_CAMPAIGN_ID_LENGTH, "campaign_id")

        campaign_path = self._campaign_file(campaign_id)
        if os.path.isfile(campaign_path):
            raise CampaignStoreError(
                "campaign '{0}' already exists".format(campaign_id)
            )

        now = utc_now_iso()
        campaign = Campaign(
            campaign_id=campaign_id,
            created_at=now,
            updated_at=now,
            description=(description or "")[:200],
            track_id=(track_id or "")[:48],
            firmware_version=(firmware_version or "")[:48],
            baseline_params=baseline_params or {},
            status="created",
        )
        _atomic_write_json(campaign_path, campaign.to_dict())
        return campaign

    def load_campaign(self, campaign_id: str) -> Optional[Campaign]:
        """Load campaign metadata, or None if not found."""
        _safe_identifier(campaign_id, CAMPAIGN_ID_RE, MAX_CAMPAIGN_ID_LENGTH, "campaign_id")
        data = _read_json(self._campaign_file(campaign_id))
        if not data or not isinstance(data, dict):
            return None
        return Campaign.from_dict(data)

    def update_campaign_status(self, campaign_id: str, status: str) -> Campaign:
        """Update campaign status field."""
        campaign = self.load_campaign(campaign_id)
        if campaign is None:
            raise CampaignStoreError("campaign '{0}' not found".format(campaign_id))
        campaign.status = status
        campaign.updated_at = utc_now_iso()
        _atomic_write_json(self._campaign_file(campaign_id), campaign.to_dict())
        return campaign

    # ----------------------------------------------------------
    # Run storage (immutable)
    # ----------------------------------------------------------

    def save_run(
        self,
        campaign_id: str,
        run_id: str,
        run_data: Dict[str, Any],
    ) -> Dict[str, Any]:
        """Save a run record atomically. Runs are immutable once written.

        Args:
            campaign_id: Validated campaign identifier.
            run_id: Validated run identifier.
            run_data: Run data dict (must include 'schema_version').

        Returns:
            Run data dict that was saved (same as run_data).

        Raises:
            CampaignStoreError: If run already exists with different content,
                                if campaign doesn't exist, or validation fails.
        """
        _safe_identifier(campaign_id, CAMPAIGN_ID_RE, MAX_CAMPAIGN_ID_LENGTH, "campaign_id")
        _safe_identifier(run_id, RUN_ID_RE, MAX_ID_LENGTH, "run_id")

        # Check campaign exists
        campaign_path = self._campaign_file(campaign_id)
        if not os.path.isfile(campaign_path):
            raise CampaignStoreError(
                "campaign '{0}' not found; create it first".format(campaign_id)
            )

        # Tag the run data with schema metadata
        enriched = dict(run_data)
        enriched.setdefault("schema_version", CAMPAIGN_SCHEMA_VERSION)
        enriched.setdefault("campaign_id", campaign_id)
        enriched.setdefault("run_id", run_id)

        run_path = self._run_file(campaign_id, run_id)
        os.makedirs(os.path.dirname(run_path), exist_ok=True)

        if os.path.isfile(run_path):
            existing = _read_json(run_path, {})
            if existing != enriched:
                raise CampaignStoreError(
                    "run '{0}' already exists with different content; "
                    "runs are immutable".format(run_id)
                )
            # Idempotent: same content, return existing
            return existing

        _atomic_write_json(run_path, enriched)
        return enriched

    def load_run(self, campaign_id: str, run_id: str) -> Optional[Dict[str, Any]]:
        """Load a single run record."""
        _safe_identifier(campaign_id, CAMPAIGN_ID_RE, MAX_CAMPAIGN_ID_LENGTH, "campaign_id")
        _safe_identifier(run_id, RUN_ID_RE, MAX_ID_LENGTH, "run_id")
        return _read_json(self._run_file(campaign_id, run_id))

    def list_runs(self, campaign_id: str) -> List[Dict[str, Any]]:
        """List all run summaries for a campaign, sorted by run_id."""
        _safe_identifier(campaign_id, CAMPAIGN_ID_RE, MAX_CAMPAIGN_ID_LENGTH, "campaign_id")
        run_dir = self._run_dir(campaign_id)
        if not os.path.isdir(run_dir):
            return []
        runs = []
        for name in sorted(os.listdir(run_dir)):
            if not name.endswith(".json"):
                continue
            run = _read_json(os.path.join(run_dir, name), {})
            if isinstance(run, dict) and run.get("run_id"):
                runs.append(run)
        return runs

    # ----------------------------------------------------------
    # Candidate decisions (append-only history)
    # ----------------------------------------------------------

    def save_decision(
        self,
        campaign_id: str,
        version: int,
        decision_data: Dict[str, Any],
    ) -> Dict[str, Any]:
        """Save a candidate decision. Historical — each version can only be written once.

        Args:
            campaign_id: Validated campaign identifier.
            version: Positive integer version of the candidate.
            decision_data: Decision data (status, reason, stats, etc.).

        Returns:
            Saved decision data dict.

        Raises:
            CampaignStoreError: If version already exists with different content,
                                or if campaign doesn't exist.
        """
        _safe_identifier(campaign_id, CAMPAIGN_ID_RE, MAX_CAMPAIGN_ID_LENGTH, "campaign_id")
        _validate_version(version)

        campaign_path = self._campaign_file(campaign_id)
        if not os.path.isfile(campaign_path):
            raise CampaignStoreError(
                "campaign '{0}' not found".format(campaign_id)
            )

        enriched = dict(decision_data)
        enriched.setdefault("schema_version", CAMPAIGN_SCHEMA_VERSION)
        enriched.setdefault("campaign_id", campaign_id)
        enriched["version"] = version

        candidate_path = self._candidate_file(campaign_id, version)
        os.makedirs(os.path.dirname(candidate_path), exist_ok=True)

        if os.path.isfile(candidate_path):
            existing = _read_json(candidate_path, {})
            if existing != enriched:
                raise CampaignStoreError(
                    "candidate version {0} already exists with different content; "
                    "decisions are historical".format(version)
                )
            return existing

        _atomic_write_json(candidate_path, enriched)
        return enriched

    def load_decision(self, campaign_id: str, version: int) -> Optional[Dict[str, Any]]:
        """Load a single candidate decision."""
        _safe_identifier(campaign_id, CAMPAIGN_ID_RE, MAX_CAMPAIGN_ID_LENGTH, "campaign_id")
        _validate_version(version)
        return _read_json(self._candidate_file(campaign_id, version))

    def list_decisions(self, campaign_id: str) -> List[Dict[str, Any]]:
        """List all candidate decisions for a campaign, sorted by version."""
        _safe_identifier(campaign_id, CAMPAIGN_ID_RE, MAX_CAMPAIGN_ID_LENGTH, "campaign_id")
        cand_dir = self._candidate_dir(campaign_id)
        if not os.path.isdir(cand_dir):
            return []
        decisions = []
        for name in sorted(os.listdir(cand_dir)):
            if not name.endswith(".json"):
                continue
            dec = _read_json(os.path.join(cand_dir, name), {})
            if isinstance(dec, dict) and dec.get("version") is not None:
                decisions.append(dec)
        return decisions

    # ----------------------------------------------------------
    # Report
    # ----------------------------------------------------------

    def save_report(self, campaign_id: str, report_data: Dict[str, Any]) -> Dict[str, Any]:
        """Final campaign report. Overwritable (convenience for progressive updates)."""
        _safe_identifier(campaign_id, CAMPAIGN_ID_RE, MAX_CAMPAIGN_ID_LENGTH, "campaign_id")
        enriched = dict(report_data)
        enriched.setdefault("schema_version", CAMPAIGN_SCHEMA_VERSION)
        enriched.setdefault("campaign_id", campaign_id)
        enriched["updated_at"] = utc_now_iso()
        _atomic_write_json(self._report_file(campaign_id), enriched)
        return enriched

    def load_report(self, campaign_id: str) -> Optional[Dict[str, Any]]:
        """Load the campaign report."""
        _safe_identifier(campaign_id, CAMPAIGN_ID_RE, MAX_CAMPAIGN_ID_LENGTH, "campaign_id")
        return _read_json(self._report_file(campaign_id))

    def list_campaigns(self) -> List[str]:
        """List all campaign IDs sorted by name."""
        campaigns_root = os.path.join(self._data_root, "campaigns")
        if not os.path.isdir(campaigns_root):
            return []
        ids = []
        for name in sorted(os.listdir(campaigns_root)):
            camp_dir = os.path.join(campaigns_root, name)
            if os.path.isdir(camp_dir) and os.path.isfile(
                os.path.join(camp_dir, "campaign.json")
            ):
                ids.append(name)
        return ids

    # ----------------------------------------------------------
    # Content validation
    # ----------------------------------------------------------

    @staticmethod
    def is_campaign_json(data: Dict[str, Any]) -> bool:
        """Check if a JSON dict is a valid campaign record (not legacy Task 2)."""
        return bool(data and isinstance(data, dict) and data.get("schema_version") == CAMPAIGN_SCHEMA_VERSION and "campaign_id" in data)
