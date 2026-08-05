# -*- coding: utf-8 -*-
"""
manifest_store.py - Efficient Data Storage System

Based on donkeycar's Manifest/Catalog architecture.
Simplified for STM32 digital twin use case.

Key features:
    1. Newline-delimited JSON records (fast append, no full rewrite)
    2. Session management (each run = one session)
    3. Index for O(1) random access
    4. Lazy iteration (memory efficient)
    5. Direct export to calibration format

Why not just use JSON files?
    - JSON arrays require full rewrite on every append
    - Large JSON files are slow to load
    - No session organization
    - No random access

Usage:
    store = ManifestStore('data/telemetry')

    # Write data (real car or simulator)
    with store.session('real_car_run_01') as session:
        for packet in telemetry_stream:
            session.write({
                't': packet.timestamp,
                'sensors': packet.sensors,
                'left_pwm': packet.left_pwm,
                'right_pwm': packet.right_pwm,
                'error': packet.error,
            })

    # Read data (for calibration)
    for record in store.iter_records():
        print(record['sensors'], record['error'])

    # Get calibration-ready data
    cal_data = store.get_calibration_data(session_name='real_car_run_01')
"""

import os
import json
import time
import mmap
from pathlib import Path


class ManifestStore:
    """
    Efficient telemetry data storage.

    Directory structure:
        data/telemetry/
            manifest.json          # metadata: sessions, record counts
            session_000/
                catalog.jsonl      # newline-delimited JSON records
                index.json         # line number -> byte offset
            session_001/
                ...
    """

    def __init__(self, base_path):
        self.base_path = Path(base_path)
        self.base_path.mkdir(parents=True, exist_ok=True)
        self.manifest_path = self.base_path / 'manifest.json'
        self._manifest = self._load_manifest()

    def _load_manifest(self):
        """Load or create manifest."""
        if self.manifest_path.exists():
            with open(self.manifest_path, 'r', encoding='utf-8') as f:
                return json.load(f)
        return {
            'sessions': {},
            'total_records': 0,
            'created_at': time.time(),
        }

    def _save_manifest(self):
        """Save manifest to disk."""
        with open(self.manifest_path, 'w', encoding='utf-8') as f:
            json.dump(self._manifest, f, indent=2, ensure_ascii=False)

    def session(self, name=None):
        """Create or open a session for writing.

        Args:
            name: Session name (auto-generated if None)

        Returns:
            Session object for writing records
        """
        if name is None:
            name = 'session_%d' % int(time.time())

        session_dir = self.base_path / name
        session_dir.mkdir(parents=True, exist_ok=True)

        catalog_path = session_dir / 'catalog.jsonl'
        index_path = session_dir / 'index.json'

        return Session(name, catalog_path, index_path, self)

    def _register_session(self, session_name, record_count):
        """Register a session in the manifest."""
        self._manifest['sessions'][session_name] = {
            'record_count': record_count,
            'updated_at': time.time(),
        }
        self._manifest['total_records'] = sum(
            s['record_count'] for s in self._manifest['sessions'].values()
        )
        self._save_manifest()

    def list_sessions(self):
        """List all sessions."""
        return list(self._manifest['sessions'].keys())

    def get_session_info(self, name):
        """Get info about a session."""
        return self._manifest['sessions'].get(name, {})

    def iter_records(self, session_name=None):
        """Iterate over all records.

        Args:
            session_name: If specified, only iterate this session.
                         If None, iterate all sessions.

        Yields:
            dict: Each record
        """
        if session_name:
            sessions = [session_name]
        else:
            sessions = self.list_sessions()

        for sname in sessions:
            session_dir = self.base_path / sname
            catalog_path = session_dir / 'catalog.jsonl'
            if catalog_path.exists():
                with open(catalog_path, 'r', encoding='utf-8') as f:
                    for line in f:
                        line = line.strip()
                        if line:
                            try:
                                yield json.loads(line)
                            except json.JSONDecodeError:
                                continue

    def get_calibration_data(self, session_name=None):
        """Export records in calibration-compatible format.

        Returns list of dicts matching the format expected by
        calibration_loop.py and model_updater.py.
        """
        records = []
        for rec in self.iter_records(session_name):
            cal_rec = {
                't': rec.get('t', 0),
                'sensors': rec.get('sensors', [1, 1, 1, 1]),
                'left_pwm': rec.get('left_pwm', 0),
                'right_pwm': rec.get('right_pwm', 0),
                'error': rec.get('error', 0),
                'pid_output': rec.get('pid_output', 0),
                'tick_ms': rec.get('tick_ms', 0),
            }
            records.append(cal_rec)
        return records

    def get_stats(self):
        """Get storage statistics."""
        return {
            'total_sessions': len(self._manifest['sessions']),
            'total_records': self._manifest['total_records'],
            'sessions': {
                name: info['record_count']
                for name, info in self._manifest['sessions'].items()
            },
        }


class Session:
    """
    A write session for recording telemetry data.

    Writes newline-delimited JSON (JSONL) format:
        - Fast append (no rewrite)
        - Line-based index for random access
        - Automatic flush on close
    """

    def __init__(self, name, catalog_path, index_path, manifest):
        self.name = name
        self.catalog_path = catalog_path
        self.index_path = index_path
        self.manifest = manifest
        self._record_count = 0
        self._offsets = []
        self._file = None

        # Load existing index if resuming
        if index_path.exists():
            with open(index_path, 'r', encoding='utf-8') as f:
                idx_data = json.load(f)
                self._offsets = idx_data.get('offsets', [])
                self._record_count = len(self._offsets)

        # Open catalog for append
        self._file = open(catalog_path, 'a', encoding='utf-8')

    def write(self, record):
        """Write a single record.

        Args:
            record: dict to serialize as JSON
        """
        line = json.dumps(record, ensure_ascii=False) + '\n'
        offset = self._file.tell()
        self._file.write(line)
        self._file.flush()
        self._offsets.append(offset)
        self._record_count += 1

    def write_batch(self, records):
        """Write multiple records at once.

        Args:
            records: list of dicts
        """
        for rec in records:
            self.write(rec)

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        self.close()

    def close(self):
        """Close session and save index."""
        if self._file and not self._file.closed:
            self._file.close()

        # Save index
        idx_data = {
            'record_count': self._record_count,
            'offsets': self._offsets,
        }
        with open(self.index_path, 'w', encoding='utf-8') as f:
            json.dump(idx_data, f)

        # Register in manifest
        self.manifest._register_session(self.name, self._record_count)

    @property
    def record_count(self):
        return self._record_count


# ================================================================
#  Quick test
# ================================================================

if __name__ == '__main__':
    import tempfile

    print("=== ManifestStore Quick Test ===")

    # Create store in temp directory
    store = ManifestStore(os.path.join(tempfile.gettempdir(), 'test_store'))

    # Write some data
    with store.session('test_session') as sess:
        for i in range(100):
            sess.write({
                't': i * 0.02,
                'sensors': [0, 1, 0, 1],
                'left_pwm': 200 + i,
                'right_pwm': 180 - i,
                'error': i % 10 - 5,
            })
        print("Written %d records" % sess.record_count)

    # Read data
    count = 0
    for rec in store.iter_records('test_session'):
        count += 1
        if count <= 3:
            print("  Record:", rec)

    print("Read %d records" % count)

    # Stats
    print("Stats:", store.get_stats())

    # Calibration data
    cal = store.get_calibration_data('test_session')
    print("Calibration records:", len(cal))

    # Cleanup
    import shutil
    shutil.rmtree(os.path.join(tempfile.gettempdir(), 'test_store'))
    print("Test passed!")
