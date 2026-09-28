"""key 明文生成（FR-2）。

格式 ``MS-XXXXX-XXXXX-XXXXX``（3 组 × 5 位，连字符分隔）；字母表
``ABCDEFGHJKMNPQRSTVWXYZ23456789``（32 字符，去 I/L/O/U/0/1 视觉混淆字符，
熵 ≈ 15×5 bit = 75 bit，口播/手抄不易错）。随机源用 ``secrets``（密码学安全，
拒绝 random 模块）。库内**明文存储**（需求「名称列 = 明文」必须可还原；哈希化
二期备案，决策台账 2026-09-28）—— UNIQUE 索引兜底 + repo.create_key 冲突重试。
"""
from __future__ import annotations

import re
import secrets

ALPHABET = 'ABCDEFGHJKMNPQRSTVWXYZ23456789'
GROUPS = 3
GROUP_LEN = 5

#: 完整明文格式（消费端输入校验 / 管理台展示一致性共用）
KEY_RE = re.compile(r'^MS-[A-Z2-9]{5}-[A-Z2-9]{5}-[A-Z2-9]{5}$')

#: 视觉混淆字符黑名单（字母表恒不含 —— 生成器字母表自查锁定）
EXCLUDED_CHARS = set('ILOU01')


def new_key_plaintext() -> str:
    """生成一个新 key 明文（secrets 随机，匹配 KEY_RE）。"""
    groups = (
        ''.join(secrets.choice(ALPHABET) for _ in range(GROUP_LEN))
        for _ in range(GROUPS)
    )
    return 'MS-' + '-'.join(groups)


def is_valid_plaintext(text: str) -> bool:
    """输入是否为合法 key 明文格式（消费端 bind/info/validate 前置校验共用）。"""
    return isinstance(text, str) and bool(KEY_RE.match(text))
