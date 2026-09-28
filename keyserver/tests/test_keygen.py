"""keygen 单测（US-001 AC3）：格式 + 唯一性 + 字母表黑名单。"""
from __future__ import annotations

from keyserver import keygen


def test_format_matches_contract():
    key = keygen.new_key_plaintext()
    assert keygen.KEY_RE.match(key), key
    assert key.startswith('MS-')
    assert len(key) == 3 + 5 * 3 + 2   # 'MS-' + 3 组 5 位 + 2 连字符


def test_generated_chars_all_from_alphabet():
    for _ in range(50):
        body = keygen.new_key_plaintext().replace('MS-', '').replace('-', '')
        assert set(body) <= set(keygen.ALPHABET)


def test_alphabet_excludes_confusable_chars():
    # 字母表 = 26 字母去 I/L/O/U + 10 数字去 0/1 = 30 字符（熵 ≈ 74 bit，FR-2）
    assert not (set(keygen.ALPHABET) & keygen.EXCLUDED_CHARS)
    assert len(keygen.ALPHABET) == 30
    assert len(set(keygen.ALPHABET)) == len(keygen.ALPHABET)


def test_thousand_generations_unique():
    keys = {keygen.new_key_plaintext() for _ in range(1000)}
    assert len(keys) == 1000


def test_is_valid_plaintext_matches_prd_regex():
    # PRD AC3 契约即 ^MS-[A-Z2-9]{5}-[A-Z2-9]{5}-[A-Z2-9]{5}$（生成器字母表是其
    # 真子集 —— 含 I/L/O 的串格式合法，只是生成器永不产生）
    assert keygen.is_valid_plaintext('MS-ABCDE-FGHJK-MNPQR')
    assert keygen.is_valid_plaintext('MS-ABCIJ-FGHJK-MNPQR')
    assert not keygen.is_valid_plaintext('ms-abcde-fghjk-mnpqr')   # 小写
    assert not keygen.is_valid_plaintext('MS-ABCD-EFGHJ-KLMNP')    # 组长不足
    assert not keygen.is_valid_plaintext('MS-ABCDEF-FGHJK-MNPQR')  # 组长超出
    assert not keygen.is_valid_plaintext('XX-ABCDE-FGHJK-MNPQR')   # 前缀
    assert not keygen.is_valid_plaintext('MS-2CDE3-FGHJK-MNPQ0')   # 含 0
    assert not keygen.is_valid_plaintext('MS-ABCDE-FGHJK')         # 缺组
    assert not keygen.is_valid_plaintext('')
    assert not keygen.is_valid_plaintext(None)   # type: ignore[arg-type]
