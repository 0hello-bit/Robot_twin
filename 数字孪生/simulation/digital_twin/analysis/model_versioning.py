# -*- coding: utf-8 -*-
"""
model_versioning.py - 模型版本管理

功能:
    1. 每次 calibration 生成 model version (带参数快照)
    2. 支持 rollback 到任意历史版本
    3. 支持 A/B model comparison
    4. 版本历史持久化 (JSON)

存储结构:
    models/
    ├── versions.json          # 版本索引
    ├── v001_initial.json      # 版本 001 参数
    ├── v002_calibrated.json   # 版本 002 参数
    └── ...
"""

import json
import os
import time
import copy
import hashlib


class ModelVersion:
    """单个模型版本"""
    __slots__ = ('version_id', 'params', 'error', 'confidence',
                 'timestamp', 'description', 'parent_id', 'metadata')

    def __init__(self, version_id, params, error=0, confidence=0,
                 description='', parent_id=None, metadata=None):
        self.version_id = version_id
        self.params = copy.deepcopy(params)
        self.error = error
        self.confidence = confidence
        self.timestamp = time.time()
        self.description = description
        self.parent_id = parent_id
        self.metadata = metadata or {}

    def to_dict(self):
        return {
            'version_id': self.version_id,
            'params': self.params,
            'error': self.error,
            'confidence': self.confidence,
            'timestamp': self.timestamp,
            'description': self.description,
            'parent_id': self.parent_id,
            'metadata': self.metadata,
        }

    @classmethod
    def from_dict(cls, d):
        v = cls(d['version_id'], d['params'], d.get('error', 0),
                d.get('confidence', 0), d.get('description', ''),
                d.get('parent_id'), d.get('metadata'))
        v.timestamp = d.get('timestamp', 0)
        return v

    def param_hash(self):
        """参数指纹 (用于去重)"""
        s = json.dumps(self.params, sort_keys=True)
        return hashlib.md5(s.encode()).hexdigest()[:8]


class ModelVersionManager:
    """
    模型版本管理器。

    使用方式:
        vm = ModelVersionManager('calibration/models/')
        v1 = vm.create_version(params, error=0.5, description='initial')
        v2 = vm.create_version(params2, error=0.3, description='calibrated')
        vm.rollback(v1.version_id)
        cmp = vm.compare(v1.version_id, v2.version_id)
    """

    def __init__(self, storage_dir='calibration/models'):
        self.storage_dir = storage_dir
        self.versions = []  # list of ModelVersion
        self.current_id = None
        self._next_num = 1

        os.makedirs(storage_dir, exist_ok=True)
        self._load_index()

    def _index_path(self):
        return os.path.join(self.storage_dir, 'versions.json')

    def _version_path(self, vid):
        return os.path.join(self.storage_dir, '{}.json'.format(vid))

    def _load_index(self):
        path = self._index_path()
        if os.path.exists(path):
            with open(path, 'r', encoding='utf-8') as f:
                data = json.load(f)
            self.versions = [ModelVersion.from_dict(v) for v in data.get('versions', [])]
            self._next_num = data.get('next_num', len(self.versions) + 1)
            self.current_id = data.get('current_id')
            # Load version params from individual files
            for v in self.versions:
                vp = self._version_path(v.version_id)
                if os.path.exists(vp) and not v.params:
                    with open(vp, 'r', encoding='utf-8') as f:
                        v.params = json.load(f).get('params', {})

    def _save_index(self):
        data = {
            'versions': [v.to_dict() for v in self.versions],
            'next_num': self._next_num,
            'current_id': self.current_id,
        }
        with open(self._index_path(), 'w', encoding='utf-8') as f:
            json.dump(data, f, indent=2, ensure_ascii=False)

    def create_version(self, params, error=0, confidence=0,
                       description='', metadata=None):
        """创建新版本"""
        vid = 'v{:03d}'.format(self._next_num)
        self._next_num += 1

        v = ModelVersion(vid, params, error, confidence,
                         description, self.current_id, metadata)

        # 保存参数到独立文件
        with open(self._version_path(vid), 'w', encoding='utf-8') as f:
            json.dump({'params': params, 'error': error}, f, indent=2)

        self.versions.append(v)
        self.current_id = vid
        self._save_index()

        return v

    def get_version(self, version_id):
        """获取指定版本"""
        for v in self.versions:
            if v.version_id == version_id:
                return v
        return None

    def get_current(self):
        """获取当前版本"""
        return self.get_version(self.current_id)

    def get_all(self):
        """获取所有版本"""
        return list(self.versions)

    def rollback(self, version_id):
        """回滚到指定版本"""
        v = self.get_version(version_id)
        if v is None:
            return False
        self.current_id = version_id
        self._save_index()
        return True

    def compare(self, vid_a, vid_b):
        """
        对比两个版本。

        返回:
            dict: 哪个更好, 参数差异, 误差改善
        """
        va = self.get_version(vid_a)
        vb = self.get_version(vid_b)
        if not va or not vb:
            return {'error': 'version not found'}

        error_improvement = va.error - vb.error  # 正=VB更好
        error_pct = error_improvement / max(abs(va.error), 1e-10) * 100

        # 参数差异
        param_diff = {}
        for key in va.params:
            if key in vb.params:
                diff = vb.params[key] - va.params[key]
                param_diff[key] = {
                    'old': round(va.params[key], 6),
                    'new': round(vb.params[key], 6),
                    'change': round(diff, 6),
                    'change_pct': round(diff / max(abs(va.params[key]), 1e-10) * 100, 1),
                }

        # 置信度变化
        conf_improvement = vb.confidence - va.confidence

        return {
            'winner': vid_b if error_improvement > 0 else vid_a,
            'error_a': va.error,
            'error_b': vb.error,
            'error_improvement': round(error_improvement, 6),
            'error_improvement_pct': round(error_pct, 1),
            'confidence_a': va.confidence,
            'confidence_b': vb.confidence,
            'confidence_change': round(conf_improvement, 1),
            'param_diff': param_diff,
        }

    def get_trend(self):
        """获取版本历史趋势"""
        return [{
            'version_id': v.version_id,
            'error': v.error,
            'confidence': v.confidence,
            'timestamp': v.timestamp,
            'description': v.description,
        } for v in self.versions]

    def export_version(self, version_id, filepath):
        """导出版本到文件"""
        v = self.get_version(version_id)
        if not v:
            return False
        with open(filepath, 'w', encoding='utf-8') as f:
            json.dump(v.to_dict(), f, indent=2, ensure_ascii=False)
        return True