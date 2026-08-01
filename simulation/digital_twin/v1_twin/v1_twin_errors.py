"""V1 数字孪生领域错误类型 (Task 4B-0)。

与旧孪生错误体系隔离；v1_twin 命名空间只使用本模块中的错误类型。
"""


class V1TwinError(Exception):
    """V1 数字孪生领域错误基类。"""


class V1SchemaError(V1TwinError):
    """Schema 校验 / 反序列化错误。"""


class V1CalibrationHoldoutOverlapError(V1SchemaError):
    """校准集与 holdout 的 run_id 交集非空（纲领 §12 第三项硬隔离）。"""


class V1IsolationError(V1TwinError):
    """v1_twin 命名空间违反旧模型隔离规则。"""
