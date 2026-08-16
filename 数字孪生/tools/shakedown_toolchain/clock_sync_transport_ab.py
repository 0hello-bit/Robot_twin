"""Bounded TCP/UDP ClockSync-only transport attribution experiment.

This tool sends only existing Q frames. It never sends START, STOP, health,
telemetry, or ESP AT commands. TCP and UDP runs are intentionally separate;
the UDP path is an experiment probe, not a stream migration.
"""

from __future__ import annotations

import argparse
import json
import select
import socket
import sys
import time
from pathlib import Path


_ROOT = Path(__file__).resolve().parents[2]
_DIGITAL_TWIN = _ROOT / "simulation" / "digital_twin"
sys.path.insert(0, str(_DIGITAL_TWIN))

from real_world.frame_parser import FrameParser  # noqa: E402
from real_world.runtime_protocol import (  # noqa: E402
    ClockSyncReply,
    ClockSyncProbe,
    ProtocolError,
    parse_command,
    parse_clock_sync_reply,
)
from v1_twin.v1_twin_causal_sync import build_causal_sync_report  # noqa: E402
from v1_twin.clock_sync_transport import (  # noqa: E402
    ClockSyncTransportObservation,
    ClockSyncTransportProfile,
    summarize_clock_sync_transport,
)


PC_CLOCK_SOURCE = "perf_counter_ns"


def _now_ns():
    return time.perf_counter_ns()


def _wall_now_ns():
    return time.time_ns()


class ClockSyncReplyLedger:
    """Account for every primary Q and every associated T outcome."""

    def __init__(self, transport):
        if transport not in ("tcp", "udp"):
            raise ValueError("transport must be tcp or udp")
        self.transport = transport
        self._pending = {}
        self._observations = []
        self._by_sequence = {}
        self._unmatched_replies = []

    def begin(self, sequence, pc_tx_ns):
        sequence = int(sequence)
        pc_tx_ns = int(pc_tx_ns)
        if sequence <= 0 or pc_tx_ns < 0:
            raise ValueError("sequence and pc_tx_ns must be positive/non-negative")
        if self._pending:
            raise ValueError("only one outstanding clock probe is allowed")
        if sequence in self._by_sequence:
            raise ValueError("clock probe sequence was already used")
        self._pending[sequence] = {"sequence": sequence, "pc_tx_ns": pc_tx_ns}

    def timeout(self, sequence, pc_timeout_ns):
        sequence = int(sequence)
        pending = self._pending.pop(sequence, None)
        if pending is None:
            raise ValueError("clock probe sequence is not pending")
        observation = {
            "transport": self.transport,
            "sequence": sequence,
            "pc_tx_ns": int(pending["pc_tx_ns"]),
            "pc_timeout_ns": int(pc_timeout_ns),
            "pc_rx_ns": None,
            "matched": False,
            "outcome": "timeout",
            "late_reply": False,
            "duplicate_count": 0,
            "reordered": False,
            "mcu_rx_tick_ms": None,
            "mcu_tx_tick_ms": None,
            "rtt_total_ns": None,
            "rtt_transport_ns": None,
            "pc_clock_source": PC_CLOCK_SOURCE,
        }
        self._by_sequence[sequence] = len(self._observations)
        self._observations.append(observation)
        return observation

    @staticmethod
    def _decode_reply(line):
        if isinstance(line, bytes):
            line = line.decode("ascii")
        if not isinstance(line, str):
            raise ValueError("clock reply must be text or ASCII bytes")
        return parse_clock_sync_reply(line)

    @staticmethod
    def _rtt_fields(pending, reply, pc_rx_ns):
        total = int(pc_rx_ns) - int(pending["pc_tx_ns"])
        device_interval = (
            int(reply.mcu_tx_tick_ms) - int(reply.mcu_rx_tick_ms)
        ) * 1_000_000
        return total, total - device_interval

    def receive(self, line, pc_rx_ns):
        """Consume one valid T frame and return its classification."""
        reply = self._decode_reply(line)
        pc_rx_ns = int(pc_rx_ns)
        if pc_rx_ns < 0:
            raise ValueError("pc_rx_ns must be non-negative")

        pending = self._pending.pop(reply.sequence, None)
        if pending is not None:
            total, transport = self._rtt_fields(pending, reply, pc_rx_ns)
            observation = {
                "transport": self.transport,
                "sequence": int(reply.sequence),
                "pc_tx_ns": int(pending["pc_tx_ns"]),
                "pc_timeout_ns": None,
                "pc_rx_ns": pc_rx_ns,
                "matched": True,
                "outcome": "matched",
                "late_reply": False,
                "duplicate_count": 0,
                "reordered": False,
                "mcu_rx_tick_ms": int(reply.mcu_rx_tick_ms),
                "mcu_tx_tick_ms": int(reply.mcu_tx_tick_ms),
                "rtt_total_ns": total,
                "rtt_transport_ns": transport,
                "pc_clock_source": PC_CLOCK_SOURCE,
            }
            self._by_sequence[reply.sequence] = len(self._observations)
            self._observations.append(observation)
            return "matched"

        index = self._by_sequence.get(reply.sequence)
        if index is not None:
            observation = self._observations[index]
            if observation["matched"]:
                observation["duplicate_count"] += 1
                outcome = "duplicate"
            else:
                total, transport = self._rtt_fields(observation, reply, pc_rx_ns)
                observation["pc_rx_ns"] = pc_rx_ns
                observation["mcu_rx_tick_ms"] = int(reply.mcu_rx_tick_ms)
                observation["mcu_tx_tick_ms"] = int(reply.mcu_tx_tick_ms)
                observation["rtt_total_ns"] = total
                observation["rtt_transport_ns"] = transport
                observation["late_reply"] = True
                observation["outcome"] = "late_reply"
                outcome = "late_reply"
            self._unmatched_replies.append({
                "transport": self.transport,
                "sequence": int(reply.sequence),
                "pc_rx_ns": pc_rx_ns,
                "line": line.decode("ascii") if isinstance(line, bytes) else line,
                "reason": outcome,
            })
            return outcome

        self._unmatched_replies.append({
            "transport": self.transport,
            "sequence": int(reply.sequence),
            "pc_rx_ns": pc_rx_ns,
            "line": line.decode("ascii") if isinstance(line, bytes) else line,
            "reason": "unknown",
        })
        return "unknown"

    def pending_sequences(self):
        return sorted(self._pending)

    def observations(self):
        return [dict(item) for item in self._observations]

    def is_matched(self, sequence):
        index = self._by_sequence.get(int(sequence))
        return bool(
            index is not None and self._observations[index]["matched"]
        )

    def unmatched_replies(self):
        return [dict(item) for item in self._unmatched_replies]

    def _contract_observations(self):
        result = []
        for item in self._observations:
            if item["matched"]:
                transport_rtt = item["rtt_transport_ns"]
                result.append(ClockSyncTransportObservation(
                    sequence=item["sequence"],
                    pc_tx_ns=item["pc_tx_ns"],
                    pc_rx_ns=item["pc_rx_ns"],
                    matched=True,
                    rtt_transport_ns=(
                        transport_rtt
                        if transport_rtt is not None and transport_rtt >= 0
                        else None
                    ),
                    duplicate_count=item["duplicate_count"],
                    reordered=item["reordered"],
                ))
            else:
                result.append(ClockSyncTransportObservation(
                    sequence=item["sequence"],
                    pc_tx_ns=item["pc_tx_ns"],
                    pc_rx_ns=item["pc_rx_ns"],
                    matched=False,
                    late_reply=item["late_reply"],
                ))
        return result

    def summary(self):
        all_items = self._contract_observations()
        summary = summarize_clock_sync_transport(all_items)
        summary["invalid_transport_rtt_count"] = sum(
            1 for item in self._observations
            if item["matched"] and (
                item["rtt_transport_ns"] is None
                or item["rtt_transport_ns"] < 0
            )
        )
        summary["pending_count"] = len(self._pending)
        return summary

    def causal_records(self):
        records = []
        for item in self._observations:
            if not item["matched"]:
                continue
            if item["mcu_rx_tick_ms"] is None:
                continue
            records.append({
                "sequence": item["sequence"],
                "pc_tx_ns": item["pc_tx_ns"],
                "mcu_rx_tick_ms": item["mcu_rx_tick_ms"],
                "mcu_tx_tick_ms": item["mcu_tx_tick_ms"],
                "pc_rx_ns": item["pc_rx_ns"],
                "sample_role": "formal",
                "included_in_fit": True,
            })
        return records

    def to_dict(self):
        return {
            "transport": self.transport,
            "pc_clock_source": PC_CLOCK_SOURCE,
            "observations": self.observations(),
            "unmatched_replies": self.unmatched_replies(),
            "pending_sequences": self.pending_sequences(),
            "summary": self.summary(),
        }


def build_udp_smoke_verdict(result, control_commands_sent):
    """Classify one UDP Q/T smoke run without inferring internal boundaries."""
    reasons = []
    raw_io = result.get("raw_io") or {}
    events = raw_io.get("events") or []
    tx_events = [event for event in events if event.get("dir") == "TX"]
    summary = ((result.get("ledger") or {}).get("summary") or {})

    if result.get("transport") != "udp":
        reasons.append("transport must be udp")
    if result.get("count_requested") != 1:
        reasons.append("count_requested must be 1")
    if control_commands_sent != []:
        reasons.append("control_commands_sent must be empty")
    if result.get("connection_error") is not None:
        reasons.append("socket execution failed")
    if raw_io.get("n_send") != 1 or len(tx_events) != 1:
        reasons.append("exactly one TX event is required")

    payload_valid = False
    sequence = None
    if len(tx_events) == 1:
        try:
            payload = bytes.fromhex(tx_events[0]["bytes_hex"]).decode("ascii")
            parsed = parse_command(payload)
            payload_valid = isinstance(parsed, ClockSyncProbe)
            sequence = parsed.sequence if payload_valid else None
            if ("sequence" in tx_events[0] and
                    tx_events[0]["sequence"] != sequence):
                payload_valid = False
                reasons.append("TX sequence metadata does not match payload")
        except (KeyError, TypeError, ValueError, UnicodeDecodeError,
                ProtocolError):
            payload_valid = False
    if not payload_valid:
        reasons.append("TX payload is not one valid Q frame")

    if summary.get("sent_count") != 1:
        reasons.append("ledger sent_count must be 1")
    matched = summary.get("matched_count") == 1
    if matched and summary.get("sent_count") != 1:
        matched = False

    structurally_valid = not reasons
    if not structurally_valid:
        verdict = "INVALID"
        roundtrip = "INSUFFICIENT EVIDENCE"
    elif matched:
        verdict = "PASS"
        roundtrip = "VERIFIED"
    else:
        verdict = "FAIL"
        roundtrip = "FAIL"

    return {
        "verdict": verdict,
        "roundtrip": roundtrip,
        "internal_boundary": "INSUFFICIENT EVIDENCE",
        "sequence": sequence,
        "reasons": reasons,
    }


class TcpClockSyncStream:
    """Extract T lines from the existing mixed TCP ASCII/binary stream."""

    def __init__(self, on_reply):
        self._frame_parser = FrameParser()
        self._ascii = bytearray()
        self._on_reply = on_reply

    def feed(self, data, arrival_pc_ns):
        for value in data:
            if self._frame_parser._state != FrameParser.S_IDLE:
                self._frame_parser.feed(value)
                continue
            if value == 0xAA:
                self._frame_parser.feed(value)
                continue
            if value == 0x0A:
                self._ascii.append(value)
                line = self._ascii.decode("ascii", errors="replace")
                self._ascii.clear()
                if line.startswith("T,"):
                    self._on_reply(line, arrival_pc_ns)
            elif value == 0x0D:
                continue
            elif 0x20 <= value <= 0x7E:
                self._ascii.append(value)
            else:
                self._ascii.clear()


def _raw_event(direction, data, pc_ns, **extra):
    event = {
        "dir": direction,
        "pc_ns": int(pc_ns),
        "pc_clock_source": PC_CLOCK_SOURCE,
        "wall_time_ns": _wall_now_ns(),
        "n_bytes": len(data),
        "bytes_hex": bytes(data).hex(),
    }
    event.update(extra)
    return event


def _recv_until(sock, transport, ledger, parser, raw_events, deadline_ns,
                parse_errors, stop_on_match=True, expected_sequence=None):
    matched = False
    while _now_ns() < deadline_ns:
        remaining_s = max(0.0, (deadline_ns - _now_ns()) / 1_000_000_000.0)
        readable, _, _ = select.select([sock], [], [], min(0.02, remaining_s))
        if not readable:
            continue
        arrival_ns = _now_ns()
        try:
            if transport == "tcp":
                data = sock.recv(4096)
                if not data:
                    raw_events.append(_raw_event("RX_EOF", b"", arrival_ns))
                    break
                raw_events.append(_raw_event("RX", data, arrival_ns))
                parser.feed(data, arrival_ns)
                matched = (
                    expected_sequence is not None
                    and ledger.is_matched(expected_sequence)
                )
            else:
                data, address = sock.recvfrom(4096)
                raw_events.append(_raw_event(
                    "RX", data, arrival_ns, peer=[address[0], address[1]]
                ))
                try:
                    outcome = ledger.receive(data, arrival_ns)
                    matched = matched or outcome == "matched"
                except (ProtocolError, UnicodeDecodeError, ValueError) as exc:
                    parse_errors.append({
                        "pc_rx_ns": arrival_ns,
                        "bytes_hex": data.hex(),
                        "error": repr(exc),
                    })
        except OSError as exc:
            parse_errors.append({
                "pc_rx_ns": arrival_ns,
                "stage": "recv",
                "error": repr(exc),
            })
            break
        if stop_on_match and matched:
            break
    return matched


def _run_one_probe(sock, transport, target, ledger, parser, raw_events, sequence,
                   period_s, timeout_s, parse_errors):
    pc_tx_ns = _now_ns()
    payload = ClockSyncProbe(sequence).encode().encode("ascii")
    ledger.begin(sequence, pc_tx_ns)
    try:
        if transport == "tcp":
            sock.sendall(payload)
        else:
            sock.sendto(payload, target)
    except Exception:
        ledger._pending.pop(sequence, None)
        raise
    raw_events.append(_raw_event("TX", payload, pc_tx_ns,
                                 sequence=int(sequence)))

    timeout_deadline_ns = pc_tx_ns + int(timeout_s * 1_000_000_000)
    matched = _recv_until(
        sock, transport, ledger, parser, raw_events, timeout_deadline_ns,
        parse_errors, stop_on_match=True, expected_sequence=sequence,
    )
    if not matched and sequence in ledger.pending_sequences():
        ledger.timeout(sequence, _now_ns())

    # Keep the probe cadence stable and drain duplicates before the next Q.
    scheduled_next_ns = pc_tx_ns + int(period_s * 1_000_000_000)
    if _now_ns() < scheduled_next_ns:
        _recv_until(
            sock, transport, ledger, parser, raw_events, scheduled_next_ns,
            parse_errors, stop_on_match=False,
        )


def _connect_socket(host, port, transport, udp_listen_port=None):
    if transport == "tcp":
        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        sock.settimeout(3.0)
        sock.connect((host, int(port)))
        sock.setblocking(False)
        return sock
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    sock.bind(("0.0.0.0", int(udp_listen_port)))
    sock.setblocking(False)
    return sock


def run_transport(*, host, transport, tcp_port=8888, udp_target_port=9998,
                  udp_listen_port=9999, count=16, period_s=0.25,
                  timeout_s=1.0, late_grace_s=0.5, sequence_start=1):
    profile = ClockSyncTransportProfile(transport)
    profile.validate()
    ledger = ClockSyncReplyLedger(transport)
    raw_events = []
    parse_errors = []
    sock = None
    connection_error = None

    try:
        target_port = tcp_port if transport == "tcp" else udp_target_port
        sock = _connect_socket(
            host, target_port, transport,
            udp_listen_port=udp_listen_port,
        )
        target = (host, int(target_port))

        def on_tcp_reply(line, arrival_ns):
            try:
                ledger.receive(line, arrival_ns)
            except (ProtocolError, UnicodeDecodeError, ValueError) as exc:
                parse_errors.append({
                    "pc_rx_ns": int(arrival_ns),
                    "line": line,
                    "error": repr(exc),
                })

        parser = TcpClockSyncStream(on_tcp_reply) if transport == "tcp" else None
        for offset in range(int(count)):
            sequence = int(sequence_start) + offset
            _run_one_probe(
                sock, transport, target, ledger, parser, raw_events, sequence,
                float(period_s), float(timeout_s), parse_errors,
            )

        if ledger.pending_sequences():
            for sequence in ledger.pending_sequences():
                ledger.timeout(sequence, _now_ns())

        grace_deadline = _now_ns() + int(late_grace_s * 1_000_000_000)
        _recv_until(
            sock, transport, ledger, parser, raw_events, grace_deadline,
            parse_errors, stop_on_match=False,
        )
    except Exception as exc:
        connection_error = repr(exc)
        for sequence in ledger.pending_sequences():
            ledger.timeout(sequence, _now_ns())
    finally:
        if sock is not None:
            try:
                sock.close()
            except OSError:
                pass

    causal_records = ledger.causal_records()
    causal_sync = build_causal_sync_report(causal_records)
    result = {
        "transport": transport,
        "profile": profile.to_dict(),
        "host": host,
        "tcp_port": int(tcp_port),
        "udp_target_port": int(udp_target_port),
        "udp_listen_port": int(udp_listen_port),
        "count_requested": int(count),
        "period_s": float(period_s),
        "timeout_s": float(timeout_s),
        "late_grace_s": float(late_grace_s),
        "connection_error": connection_error,
        "parse_errors": parse_errors,
        "ledger": ledger.to_dict(),
        "causal_sync_input_count": len(causal_records),
        "causal_sync": causal_sync,
        "raw_io": {
            "n_send": sum(1 for event in raw_events if event["dir"] == "TX"),
            "n_recv": sum(1 for event in raw_events if event["dir"] == "RX"),
            "events": raw_events,
        },
    }
    if transport == "udp":
        matched = result["ledger"]["summary"]["matched_count"]
        result["udp_capability_evidence"] = {
            "udp_supported": bool(matched),
            "udp_capability_source": (
                "observed_udp_q_t_round_trip" if matched else None
            ),
            "ipd_header_mode": "link_id_length" if matched else None,
            "verdict": "VERIFIED" if matched else "INSUFFICIENT EVIDENCE",
        }
    return result


def _run_id():
    return time.strftime("c%y%m%d%H%M%S") + "_{:03d}".format(
        _now_ns() % 1000
    )


def write_report(out_dir, report):
    out_path = Path(out_dir)
    out_path.mkdir(parents=True, exist_ok=True)
    (out_path / "transport_ab_report.json").write_text(
        json.dumps(report, indent=2, ensure_ascii=False), encoding="utf-8"
    )
    for transport, result in report["runs"].items():
        run_dir = out_path / transport
        run_dir.mkdir(parents=True, exist_ok=True)
        (run_dir / "raw_io.json").write_text(
            json.dumps(result["raw_io"], indent=2, ensure_ascii=False),
            encoding="utf-8",
        )
        (run_dir / "clock_sync_ledger.json").write_text(
            json.dumps(result["ledger"], indent=2, ensure_ascii=False),
            encoding="utf-8",
        )
    return out_path / "transport_ab_report.json"


def build_arg_parser():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--smoke", action="store_true",
        help="send exactly one UDP Q and return non-zero unless T matches",
    )
    parser.add_argument("--host", default="192.168.110.236")
    parser.add_argument("--tcp-port", type=int, default=8888)
    parser.add_argument("--udp-target-port", type=int, default=9998)
    parser.add_argument("--udp-listen-port", type=int, default=9999)
    parser.add_argument("--count", type=int, default=None)
    parser.add_argument("--period", type=float, default=0.25)
    parser.add_argument("--timeout", type=float, default=1.0)
    parser.add_argument("--late-grace", type=float, default=0.5)
    parser.add_argument("--sequence-start", type=int, default=1)
    parser.add_argument("--transport", choices=("tcp", "udp", "both"),
                        default=None)
    parser.add_argument("--out", default=None)
    return parser


def main(argv=None):
    args = build_arg_parser().parse_args(argv)
    if args.period <= 0 or args.timeout <= 0:
        raise SystemExit("count, period, and timeout must be positive")
    if args.smoke:
        if args.transport not in (None, "udp"):
            raise SystemExit("--smoke requires --transport udp")
        if args.count not in (None, 1):
            raise SystemExit("--smoke requires exactly one probe")
        count = 1
        transport = "udp"
        transports = (transport,)
    else:
        count = 16 if args.count is None else args.count
        if count <= 0:
            raise SystemExit("count, period, and timeout must be positive")
        transport = "both" if args.transport is None else args.transport
        transports = ("tcp", "udp") if transport == "both" else (transport,)
    report = {
        "schema_version": 1,
        "task": (
            "UDP ClockSync smoke, one Q/T exchange"
            if args.smoke else
            "ClockSync transport attribution, Q/T only"
        ),
        "mode": "clock_sync_only",
        "smoke": bool(args.smoke),
        "control_commands_sent": [],
        "payload_contract": "q_t_v1",
        "pc_clock_source": PC_CLOCK_SOURCE,
        "single_outstanding": True,
        "primary_retries": False,
        "telemetry_migrated": False,
        "health_migrated": False,
        "control_migrated": False,
        "runs": {},
    }
    for transport in transports:
        print("starting {0} ClockSync-only run ({1} probes)".format(
            transport, count
        ), flush=True)
        report["runs"][transport] = run_transport(
            host=args.host,
            transport=transport,
            tcp_port=args.tcp_port,
            udp_target_port=args.udp_target_port,
            udp_listen_port=args.udp_listen_port,
            count=count,
            period_s=args.period,
            timeout_s=args.timeout,
            late_grace_s=args.late_grace,
            sequence_start=args.sequence_start,
        )
        if args.smoke:
            report["runs"][transport]["smoke_verdict"] = (
                build_udp_smoke_verdict(
                    report["runs"][transport],
                    report["control_commands_sent"],
                )
            )
        summary = report["runs"][transport]["ledger"]["summary"]
        print("{0}: sent={1} matched={2} lost={3} rtt_p95_ms={4}".format(
            transport,
            summary["sent_count"],
            summary["matched_count"],
            summary["lost_count"],
            (None if summary["total_rtt_p95_ns"] is None else
             summary["total_rtt_p95_ns"] / 1_000_000.0),
        ), flush=True)

    out_dir = args.out or str(
        _ROOT / "docs" / "evidence" /
        ("v1_b3_clock_sync_transport_ab_" + time.strftime("%Y%m%d")) /
        _run_id()
    )
    report["out_dir"] = out_dir
    report_path = write_report(out_dir, report)
    print("report:", report_path)
    if args.smoke:
        smoke_verdict = report["runs"]["udp"]["smoke_verdict"]
        print(
            "smoke: verdict={0} roundtrip={1} internal_boundary={2}".format(
                smoke_verdict["verdict"],
                smoke_verdict["roundtrip"],
                smoke_verdict["internal_boundary"],
            ),
            flush=True,
        )
        return 0 if smoke_verdict["verdict"] == "PASS" else 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
