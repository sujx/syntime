"""AK/SK 信封加密基础件（engineering-conventions §4.2，PRD 4.5-1）。

主密钥（KEK，32 字节 AES-256）托管解析顺序：
1. SYNTIME_MASTER_KEY_FILE —— 密钥文件路径（生产首选，compose secret 风格）
2. SYNTIME_MASTER_KEY     —— 环境变量直接给 base64 密钥
3. DEBUG 下的本地兜底文件 backend/.masterkey_dev（首次自动生成，gitignore）

密钥内容为 base64 编码、解码后须为 32 字节；生产环境两者皆缺时快速失败。

信封加密：DEK 不落库、由主密钥确定性推导——
    DEK = HKDF-SHA256(master_key, salt="syntime-dek:{dek_id}", info="v{key_version}")
密文格式 base64(nonce(12) || ciphertext+tag)；AAD 绑定 dek_id/key_version/字段名，
防止 AK 与 SK 密文互换或跨账号挪用。key_version 变更即换 DEK，支撑轮换重加密。
"""

import base64
import os
import secrets
import uuid
from pathlib import Path

from cryptography.exceptions import InvalidTag
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from cryptography.hazmat.primitives.kdf.hkdf import HKDF
from django.conf import settings
from django.core.exceptions import ImproperlyConfigured

_ENV_KEY = "SYNTIME_MASTER_KEY"
_ENV_KEY_FILE = "SYNTIME_MASTER_KEY_FILE"
_DEV_KEY_FILE = Path(__file__).resolve().parent.parent / ".masterkey_dev"

CURRENT_KEY_VERSION = 1
_KEY_LEN = 32
_NONCE_LEN = 12


class DecryptionError(Exception):
    """密文解密失败：主密钥不匹配、数据被篡改或上下文（dek_id/字段/版本）不符。"""


def load_master_key() -> bytes:
    """返回 32 字节主密钥；缺失或格式非法抛 ImproperlyConfigured。"""
    key_file = os.environ.get(_ENV_KEY_FILE)
    if key_file:
        return _decode_key(_read_key_file(Path(key_file)), key_file)

    key = os.environ.get(_ENV_KEY)
    if key:
        return _decode_key(key, _ENV_KEY)

    if settings.DEBUG:
        return _ensure_dev_key()

    raise ImproperlyConfigured(
        f"主密钥未配置：设置 {_ENV_KEY_FILE}（密钥文件路径）或 {_ENV_KEY}（base64 密钥）"
    )


def new_dek_id() -> str:
    """生成新的数据密钥标识（每账号一条，uuid4 hex）。"""
    return uuid.uuid4().hex


def encrypt_credential(
    plaintext: str,
    *,
    dek_id: str,
    key_version: int,
    field: str,
    master_key: bytes | None = None,
) -> str:
    """加密单条凭证，返回 base64(nonce || ct+tag) 密文。"""
    key = master_key if master_key is not None else load_master_key()
    dek = _derive_dek(key, dek_id, key_version)
    nonce = os.urandom(_NONCE_LEN)
    ciphertext = AESGCM(dek).encrypt(
        nonce, plaintext.encode("utf-8"), _aad(dek_id, key_version, field)
    )
    return base64.b64encode(nonce + ciphertext).decode("ascii")


def decrypt_credential(
    cipher_text: str,
    *,
    dek_id: str,
    key_version: int,
    field: str,
    master_key: bytes | None = None,
) -> str:
    """解密单条凭证；失败抛 DecryptionError。"""
    key = master_key if master_key is not None else load_master_key()
    try:
        raw = base64.b64decode(cipher_text, validate=True)
    except (ValueError, TypeError) as exc:
        raise DecryptionError("密文不是合法的 base64") from exc
    if len(raw) <= _NONCE_LEN:
        raise DecryptionError("密文长度非法")
    nonce, ciphertext = raw[:_NONCE_LEN], raw[_NONCE_LEN:]
    dek = _derive_dek(key, dek_id, key_version)
    try:
        plaintext = AESGCM(dek).decrypt(nonce, ciphertext, _aad(dek_id, key_version, field))
    except InvalidTag as exc:
        raise DecryptionError(
            "密文解密失败：主密钥不匹配、数据被篡改或上下文（dek_id/字段/版本）不符"
        ) from exc
    return plaintext.decode("utf-8")


def encrypt_account_credentials(ak: str, sk: str) -> tuple[str, str, str, int]:
    """加密账号 AK/SK 对，返回 (ak_cipher, sk_cipher, dek_id, key_version)。"""
    dek_id = new_dek_id()
    version = CURRENT_KEY_VERSION
    ak_cipher = encrypt_credential(ak, dek_id=dek_id, key_version=version, field="ak")
    sk_cipher = encrypt_credential(sk, dek_id=dek_id, key_version=version, field="sk")
    return ak_cipher, sk_cipher, dek_id, version


def decrypt_account_credentials(
    ak_cipher: str, sk_cipher: str, *, dek_id: str, key_version: int
) -> tuple[str, str]:
    """解密账号 AK/SK 对，返回 (ak, sk)；失败抛 DecryptionError。"""
    ak = decrypt_credential(ak_cipher, dek_id=dek_id, key_version=key_version, field="ak")
    sk = decrypt_credential(sk_cipher, dek_id=dek_id, key_version=key_version, field="sk")
    return ak, sk


def _derive_dek(master_key: bytes, dek_id: str, key_version: int) -> bytes:
    hkdf = HKDF(
        algorithm=hashes.SHA256(),
        length=_KEY_LEN,
        salt=f"syntime-dek:{dek_id}".encode(),
        info=f"v{key_version}".encode(),
    )
    return hkdf.derive(master_key)


def _aad(dek_id: str, key_version: int, field: str) -> bytes:
    return f"syntime:credential:{dek_id}:v{key_version}:{field}".encode()


def _read_key_file(path: Path) -> str:
    try:
        return path.read_text(encoding="utf-8").strip()
    except OSError as exc:
        raise ImproperlyConfigured(f"无法读取密钥文件 {path}：{exc}") from exc


def _decode_key(text: str, source: str) -> bytes:
    try:
        raw = base64.b64decode(text, validate=True)
    except (ValueError, TypeError) as exc:
        raise ImproperlyConfigured(f"主密钥来源 {source} 不是合法的 base64") from exc
    if len(raw) != 32:
        raise ImproperlyConfigured(
            f"主密钥来源 {source} 解码后须为 32 字节（AES-256），当前 {len(raw)} 字节"
        )
    return raw


def _ensure_dev_key() -> bytes:
    if _DEV_KEY_FILE.exists():
        return _decode_key(_read_key_file(_DEV_KEY_FILE), str(_DEV_KEY_FILE))
    raw = secrets.token_bytes(32)
    _DEV_KEY_FILE.write_text(base64.b64encode(raw).decode("ascii"), encoding="utf-8")
    return raw
