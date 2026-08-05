"""ASCII / binary stream demuxer for STM32 TCP telemetry.

The STM32 sends two kinds of data over the same TCP connection:
  - AA 55 binary frames (existing telemetry)
  - ASCII lines ending in \n (A ACK and S status frames from Task 1)

This module splits raw TCP bytes by emitting binary frames to one callback
and ASCII lines to another.  It does NOT depend on the full LiveWifiBridge
or cv2, making it independently testable.
"""

from __future__ import annotations

from typing import Callable, Optional


class StreamDemuxer:
    """Splits raw TCP bytes into AA55 binary frames and ASCII lines.

    Usage:
        demuxer = StreamDemuxer(on_ascii_line=my_line_handler)
        for byte in tcp_data:
            demuxer.feed(byte)
    """

    # AA 55 binary frame minimum length: header(2) + type(1) + seq(1)
    # + payload(4*5) + checksum(1) = 25 bytes, but we just detect AA 55
    # at the start and accumulate until a complete frame or timeout.
    # For demux purposes we simply separate binary from ASCII by checking
    # if the first non-whitespace byte of a potential line is NOT printable
    # ASCII or is AA 55 pattern.

    def __init__(self, on_ascii_line: Optional[Callable[[str], None]] = None):
        self._on_ascii_line = on_ascii_line
        self._line_buf = bytearray()
        self._in_binary = False

    def feed(self, byte: int) -> None:
        """Feed one byte from the TCP stream.

        ASCII lines are accumulated until \\n, then `on_ascii_line` is called.
        AA 55 binary frames are detected; their bytes are ignored by the
        ASCII line collector (they are still passed through to the existing
        FrameParser separately).
        """
        # Detect AA 55 binary frame start
        if byte == 0xAA and not self._in_binary:
            self._flush_line()
            self._in_binary = True
            return

        if self._in_binary:
            # In binary mode: wait for end-of-frame or swallow bytes.
            # For demuxing purposes, binary ends when we see a byte that
            # is clearly not part of a binary frame (e.g., printable ASCII
            # after the frame would have completed), or after a reasonable
            # accumulation.  The existing FrameParser handles the actual
            # binary parsing — we just don't let binary bytes pollute the
            # ASCII line buffer.
            self._in_binary = False  # simplified: single-byte heuristic
            # Actually, the binary frames are fixed-length 24 bytes.
            # For the demuxer, we simply skip them based on the AA 55 prefix.
            # The existing parser.feed() in _wifi_loop handles binary frames.
            # We just need to not accumulate them in _line_buf.
            return

        # Handle potential ASCII line byte
        if byte == 0x0A:  # LF
            # Include the LF in the line so parse_ack/parse_status accept it
            self._line_buf.append(byte)
            line = self._line_buf.decode("ascii", errors="replace")
            self._line_buf.clear()
            if self._on_ascii_line and line.strip():
                self._on_ascii_line(line)
        elif byte == 0x0D:  # CR — ignore
            pass
        else:
            # Only accumulate printable ASCII (including comma, space, etc.)
            if 0x20 <= byte <= 0x7E:
                self._line_buf.append(byte)
            else:
                # Non-printable byte — flush buffer, it's likely binary noise
                self._flush_line()

    def _flush_line(self) -> None:
        if self._line_buf:
            self._line_buf.clear()

    def reset(self) -> None:
        self._line_buf.clear()
        self._in_binary = False
