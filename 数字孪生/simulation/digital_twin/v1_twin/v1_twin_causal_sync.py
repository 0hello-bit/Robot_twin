"""Evidence-traceable PC/MCU clock exchange and causal sync metrics."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict, Mapping, Sequence, Tuple

import numpy as np


_EXCHANGE_FIELDS = (
    "sequence",
    "pc_tx_ns",
    "mcu_rx_tick_ms",
    "mcu_tx_tick_ms",
    "pc_rx_ns",
)


def _required_int(record: Mapping[str, Any], field: str) -> int:
    if field not in record:
        raise ValueError("missing exchange field: {0}".format(field))
    value = record[field]
    if isinstance(value, bool) or not isinstance(value, int):
        raise ValueError("exchange field {0} must be an integer".format(field))
    return int(value)


@dataclass(frozen=True)
class ClockExchangeSample:
    """One NTP-style PC -> MCU -> PC clock exchange.

    ``pc_tx_ns`` and ``pc_rx_ns`` use the host monotonic clock.  The MCU
    fields use the firmware monotonic millisecond counter.  The sample keeps
    both endpoints so path delay is measurable instead of being folded into a
    fake per-telemetry receive timestamp.
    """

    sequence: int
    pc_tx_ns: int
    mcu_rx_tick_ms: int
    mcu_tx_tick_ms: int
    pc_rx_ns: int

    def __post_init__(self) -> None:
        values = {
            "sequence": self.sequence,
            "pc_tx_ns": self.pc_tx_ns,
            "mcu_rx_tick_ms": self.mcu_rx_tick_ms,
            "mcu_tx_tick_ms": self.mcu_tx_tick_ms,
            "pc_rx_ns": self.pc_rx_ns,
        }
        for field, value in values.items():
            if isinstance(value, bool) or not isinstance(value, int):
                raise ValueError(
                    "exchange field {0} must be an integer".format(field)
                )
        if self.sequence < 0:
            raise ValueError("sequence must be non-negative")
        if self.pc_tx_ns < 0:
            raise ValueError("pc_tx_ns must be non-negative")
        if self.mcu_rx_tick_ms < 0 or self.mcu_tx_tick_ms < 0:
            raise ValueError("MCU ticks must be non-negative")
        if self.pc_rx_ns < self.pc_tx_ns:
            raise ValueError("pc_rx_ns must be >= pc_tx_ns")
        if self.mcu_tx_tick_ms < self.mcu_rx_tick_ms:
            raise ValueError("mcu_tx_tick_ms must be >= mcu_rx_tick_ms")

    @classmethod
    def from_dict(cls, record: Mapping[str, Any]) -> "ClockExchangeSample":
        if not isinstance(record, Mapping):
            raise ValueError("exchange record must be a mapping")
        values = {
            field: _required_int(record, field)
            for field in _EXCHANGE_FIELDS
        }
        return cls(**values)

    def to_dict(self) -> Dict[str, int]:
        return {
            "sequence": self.sequence,
            "pc_tx_ns": self.pc_tx_ns,
            "mcu_rx_tick_ms": self.mcu_rx_tick_ms,
            "mcu_tx_tick_ms": self.mcu_tx_tick_ms,
            "pc_rx_ns": self.pc_rx_ns,
        }


@dataclass(frozen=True)
class CausalSyncPolicy:
    """Explicit thresholds for the physical-event synchronization gate."""

    min_exchanges: int = 8
    max_rtt_p95_ns: int = 20_000_000
    max_residual_p95_ns: int = 5_000_000
    max_uncertainty_p95_ns: int = 10_000_000

    def __post_init__(self) -> None:
        values = {
            "min_exchanges": self.min_exchanges,
            "max_rtt_p95_ns": self.max_rtt_p95_ns,
            "max_residual_p95_ns": self.max_residual_p95_ns,
            "max_uncertainty_p95_ns": self.max_uncertainty_p95_ns,
        }
        for field, value in values.items():
            if isinstance(value, bool) or not isinstance(value, int):
                raise ValueError("{0} must be an integer".format(field))
            if value < 0:
                raise ValueError("{0} must be non-negative".format(field))
        if self.min_exchanges < 2:
            raise ValueError("min_exchanges must be at least 2")


def _percentile(values: Sequence[float], percentile: float) -> float:
    if not values:
        return 0.0
    return float(np.percentile(np.asarray(values, dtype=float), percentile))


@dataclass(frozen=True)
class CausalClockFit:
    """Linear mapping fitted from four-timestamp clock exchanges."""

    samples: Tuple[ClockExchangeSample, ...]
    slope_ns_per_ms: float
    offset_ns: float
    rtt_ns: Tuple[float, ...]
    residual_ns: Tuple[float, ...]
    uncertainty_ns: Tuple[float, ...]

    @classmethod
    def fit(cls, samples: Sequence[ClockExchangeSample]) -> "CausalClockFit":
        normalized = tuple(samples)
        if len(normalized) < 2:
            raise ValueError("at least 2 clock exchange samples are required")
        if any(not isinstance(sample, ClockExchangeSample)
               for sample in normalized):
            raise ValueError("samples must contain ClockExchangeSample values")
        for previous, current in zip(normalized, normalized[1:]):
            if current.sequence <= previous.sequence:
                raise ValueError("exchange sequence must be strictly increasing")

        midpoint_ticks = []
        midpoint_pc_ns = []
        rtt_ns = []
        for sample in normalized:
            round_trip_ns = (
                sample.pc_rx_ns - sample.pc_tx_ns
                - (sample.mcu_tx_tick_ms - sample.mcu_rx_tick_ms) * 1_000_000
            )
            if round_trip_ns < 0:
                raise ValueError(
                    "clock exchange has negative transport round-trip time"
                )
            midpoint_ticks.append(
                (sample.mcu_rx_tick_ms + sample.mcu_tx_tick_ms) / 2.0
            )
            midpoint_pc_ns.append((sample.pc_tx_ns + sample.pc_rx_ns) / 2.0)
            rtt_ns.append(float(round_trip_ns))

        x = np.asarray(midpoint_ticks, dtype=float)
        y = np.asarray(midpoint_pc_ns, dtype=float)
        count = float(len(x))
        sum_x = float(x.sum())
        sum_y = float(y.sum())
        sum_xx = float((x * x).sum())
        sum_xy = float((x * y).sum())
        denominator = count * sum_xx - sum_x * sum_x
        if abs(denominator) < 1e-12:
            raise ValueError("clock exchange ticks are degenerate")
        slope = (count * sum_xy - sum_x * sum_y) / denominator
        offset = (sum_y - slope * sum_x) / count
        if not np.isfinite(slope) or not np.isfinite(offset):
            raise ValueError("clock fit is not finite")

        residuals = tuple(
            float(abs(slope * tick + offset - pc_ns))
            for tick, pc_ns in zip(midpoint_ticks, midpoint_pc_ns)
        )
        uncertainty = tuple(
            float(delay / 2.0 + 0.5 * abs(slope))
            for delay in rtt_ns
        )
        return cls(
            samples=normalized,
            slope_ns_per_ms=float(slope),
            offset_ns=float(offset),
            rtt_ns=tuple(rtt_ns),
            residual_ns=residuals,
            uncertainty_ns=uncertainty,
        )

    def tick_to_pc_ns(self, tick_ms: float) -> float:
        """Map an MCU monotonic tick to the host monotonic time domain."""
        value = self.slope_ns_per_ms * float(tick_ms) + self.offset_ns
        if not np.isfinite(value):
            raise ValueError("mapped PC timestamp is not finite")
        return float(value)

    def metrics(self) -> Dict[str, float | int]:
        residuals = self.residual_ns
        rtt = self.rtt_ns
        uncertainty = self.uncertainty_ns
        residual_array = np.asarray(residuals, dtype=float)
        return {
            "sample_count": len(self.samples),
            "slope_ns_per_ms": self.slope_ns_per_ms,
            "offset_ns": self.offset_ns,
            "drift_ppm": (self.slope_ns_per_ms / 1_000_000.0 - 1.0) * 1_000_000.0,
            "rtt_min_ns": float(min(rtt)),
            "rtt_median_ns": float(np.median(np.asarray(rtt, dtype=float))),
            "rtt_p95_ns": _percentile(rtt, 95.0),
            "rtt_max_ns": float(max(rtt)),
            "residual_rms_ns": float(np.sqrt(np.mean(residual_array ** 2))),
            "residual_p95_ns": _percentile(residuals, 95.0),
            "residual_max_ns": float(max(residuals)),
            "uncertainty_p95_ns": _percentile(uncertainty, 95.0),
            "uncertainty_max_ns": float(max(uncertainty)),
        }


@dataclass(frozen=True)
class CausalSyncGateResult:
    """Independent verdict for causal clock synchronization."""

    verdict: str
    metrics: Dict[str, float | int]
    reason: str

    def to_dict(self) -> Dict[str, Any]:
        return {
            "verdict": self.verdict,
            "reason": self.reason,
            **dict(self.metrics),
        }


def evaluate_causal_sync(
    fit: CausalClockFit,
    policy: CausalSyncPolicy,
) -> CausalSyncGateResult:
    """Evaluate measured exchange quality without hiding failed samples."""
    metrics = fit.metrics()
    if int(metrics["sample_count"]) < policy.min_exchanges:
        return CausalSyncGateResult(
            verdict="INSUFFICIENT EVIDENCE",
            metrics=metrics,
            reason=(
                "too few clock exchanges: {0} < {1}"
                .format(metrics["sample_count"], policy.min_exchanges)
            ),
        )

    failures = []
    if metrics["rtt_p95_ns"] > policy.max_rtt_p95_ns:
        failures.append("rtt_p95_ns exceeds policy")
    if metrics["residual_p95_ns"] > policy.max_residual_p95_ns:
        failures.append("residual_p95_ns exceeds policy")
    if metrics["uncertainty_p95_ns"] > policy.max_uncertainty_p95_ns:
        failures.append("uncertainty_p95_ns exceeds policy")
    if failures:
        return CausalSyncGateResult(
            verdict="FAIL",
            metrics=metrics,
            reason="; ".join(failures),
        )
    return CausalSyncGateResult(
        verdict="PASS",
        metrics=metrics,
        reason="exchange count and causal clock quality thresholds pass",
    )


def build_causal_sync_report(
    exchange_records: Sequence[Mapping[str, Any]],
    policy: CausalSyncPolicy = None,
) -> Dict[str, Any]:
    """Build a fail-closed JSON-compatible causal-sync report."""
    selected_policy = policy or CausalSyncPolicy()
    records = list(exchange_records)
    if not records:
        return {
            "verdict": "INSUFFICIENT EVIDENCE",
            "reason": "no clock exchange samples recorded",
            "sample_count": 0,
            "fit": None,
            "policy": {
                "min_exchanges": selected_policy.min_exchanges,
                "max_rtt_p95_ns": selected_policy.max_rtt_p95_ns,
                "max_residual_p95_ns": selected_policy.max_residual_p95_ns,
                "max_uncertainty_p95_ns": selected_policy.max_uncertainty_p95_ns,
            },
        }
    try:
        samples = tuple(
            ClockExchangeSample.from_dict(record) for record in records
        )
        fit = CausalClockFit.fit(samples)
    except (TypeError, ValueError) as error:
        return {
            "verdict": "INSUFFICIENT EVIDENCE",
            "reason": "invalid clock exchange evidence: {0}".format(error),
            "sample_count": len(records),
            "fit": None,
        }

    result = evaluate_causal_sync(fit, selected_policy).to_dict()
    result["fit"] = "midpoint_linear"
    result["exchange_fields"] = list(_EXCHANGE_FIELDS)
    result["policy"] = {
        "min_exchanges": selected_policy.min_exchanges,
        "max_rtt_p95_ns": selected_policy.max_rtt_p95_ns,
        "max_residual_p95_ns": selected_policy.max_residual_p95_ns,
        "max_uncertainty_p95_ns": selected_policy.max_uncertainty_p95_ns,
    }
    return result


__all__ = [
    "CausalClockFit",
    "CausalSyncGateResult",
    "CausalSyncPolicy",
    "ClockExchangeSample",
    "build_causal_sync_report",
    "evaluate_causal_sync",
]
