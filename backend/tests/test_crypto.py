import base64

import pytest
from django.core.exceptions import ImproperlyConfigured

from common import crypto

KEY_A = base64.b64encode(b"a" * 32).decode()
KEY_B = base64.b64encode(b"b" * 32).decode()


def _clear_env(monkeypatch):
    monkeypatch.delenv(crypto._ENV_KEY_FILE, raising=False)
    monkeypatch.delenv(crypto._ENV_KEY, raising=False)


def test_load_from_env(monkeypatch):
    _clear_env(monkeypatch)
    monkeypatch.setenv(crypto._ENV_KEY, KEY_A)
    assert crypto.load_master_key() == b"a" * 32


def test_file_takes_precedence_over_env(monkeypatch, tmp_path):
    key_file = tmp_path / "master.key"
    key_file.write_text(KEY_B + "\n", encoding="utf-8")
    monkeypatch.setenv(crypto._ENV_KEY_FILE, str(key_file))
    monkeypatch.setenv(crypto._ENV_KEY, KEY_A)
    assert crypto.load_master_key() == b"b" * 32


def test_invalid_base64_rejected(monkeypatch):
    _clear_env(monkeypatch)
    monkeypatch.setenv(crypto._ENV_KEY, "not!base64!!!")
    with pytest.raises(ImproperlyConfigured):
        crypto.load_master_key()


def test_wrong_length_rejected(monkeypatch):
    _clear_env(monkeypatch)
    monkeypatch.setenv(crypto._ENV_KEY, base64.b64encode(b"short").decode())
    with pytest.raises(ImproperlyConfigured):
        crypto.load_master_key()


def test_missing_file_rejected(monkeypatch, tmp_path):
    monkeypatch.setenv(crypto._ENV_KEY_FILE, str(tmp_path / "absent.key"))
    with pytest.raises(ImproperlyConfigured):
        crypto.load_master_key()


def test_dev_fallback_creates_and_reuses_key(monkeypatch, tmp_path, settings):
    settings.DEBUG = True
    _clear_env(monkeypatch)
    dev_key_file = tmp_path / ".masterkey_dev"
    monkeypatch.setattr(crypto, "_DEV_KEY_FILE", dev_key_file)

    first = crypto.load_master_key()
    assert len(first) == 32
    assert dev_key_file.exists()

    assert crypto.load_master_key() == first


def test_prod_missing_key_fails_fast(monkeypatch, settings):
    _clear_env(monkeypatch)
    settings.DEBUG = False
    with pytest.raises(ImproperlyConfigured, match=crypto._ENV_KEY_FILE):
        crypto.load_master_key()


# ---- 信封加密（AES-256-GCM + HKDF DEK 推导） ----

KEY = b"k" * 32
PLAIN_AK = "LTAI5tFakeAccessKey007"
PLAIN_SK = "FakeSecret0123456789abcdef"


def test_roundtrip():
    ct = crypto.encrypt_credential(PLAIN_AK, dek_id="d1", key_version=1, field="ak", master_key=KEY)
    pt = crypto.decrypt_credential(ct, dek_id="d1", key_version=1, field="ak", master_key=KEY)
    assert pt == PLAIN_AK
    assert PLAIN_AK not in ct


def test_random_nonce_gives_different_ciphertext():
    c1 = crypto.encrypt_credential(PLAIN_AK, dek_id="d1", key_version=1, field="ak", master_key=KEY)
    c2 = crypto.encrypt_credential(PLAIN_AK, dek_id="d1", key_version=1, field="ak", master_key=KEY)
    assert c1 != c2


def test_tampered_ciphertext_raises():
    ct = crypto.encrypt_credential(PLAIN_AK, dek_id="d1", key_version=1, field="ak", master_key=KEY)
    raw = bytearray(base64.b64decode(ct))
    raw[-1] ^= 0x01
    tampered = base64.b64encode(bytes(raw)).decode()
    with pytest.raises(crypto.DecryptionError):
        crypto.decrypt_credential(tampered, dek_id="d1", key_version=1, field="ak", master_key=KEY)


def test_field_mismatch_raises():
    ct = crypto.encrypt_credential(PLAIN_AK, dek_id="d1", key_version=1, field="ak", master_key=KEY)
    with pytest.raises(crypto.DecryptionError):
        crypto.decrypt_credential(ct, dek_id="d1", key_version=1, field="sk", master_key=KEY)


def test_dek_id_mismatch_blocks_cross_account_swap():
    ct = crypto.encrypt_credential(
        PLAIN_AK, dek_id="account-a", key_version=1, field="ak", master_key=KEY
    )
    with pytest.raises(crypto.DecryptionError):
        crypto.decrypt_credential(ct, dek_id="account-b", key_version=1, field="ak", master_key=KEY)


def test_key_version_changes_derivation():
    v1 = crypto.encrypt_credential(PLAIN_AK, dek_id="d1", key_version=1, field="ak", master_key=KEY)
    v2 = crypto.encrypt_credential(PLAIN_AK, dek_id="d1", key_version=2, field="ak", master_key=KEY)
    assert v1 != v2
    with pytest.raises(crypto.DecryptionError):
        crypto.decrypt_credential(v1, dek_id="d1", key_version=2, field="ak", master_key=KEY)


def test_wrong_master_key_raises():
    ct = crypto.encrypt_credential(PLAIN_AK, dek_id="d1", key_version=1, field="ak", master_key=KEY)
    with pytest.raises(crypto.DecryptionError):
        crypto.decrypt_credential(ct, dek_id="d1", key_version=1, field="ak", master_key=b"z" * 32)


def test_invalid_base64_cipher_raises():
    with pytest.raises(crypto.DecryptionError):
        crypto.decrypt_credential(
            "not!base64!!!", dek_id="d1", key_version=1, field="ak", master_key=KEY
        )


def test_short_cipher_raises():
    short = base64.b64encode(b"\x00" * 8).decode()
    with pytest.raises(crypto.DecryptionError):
        crypto.decrypt_credential(short, dek_id="d1", key_version=1, field="ak", master_key=KEY)


def test_dek_derivation_deterministic_and_distinct():
    a1 = crypto._derive_dek(KEY, "d1", 1)
    a2 = crypto._derive_dek(KEY, "d1", 1)
    b = crypto._derive_dek(KEY, "d2", 1)
    assert a1 == a2
    assert a1 != b
    assert a1 != KEY


def test_new_dek_id_unique():
    assert crypto.new_dek_id() != crypto.new_dek_id()


def test_account_credentials_roundtrip(monkeypatch):
    _clear_env(monkeypatch)
    monkeypatch.setenv(crypto._ENV_KEY, KEY_A)
    ak_cipher, sk_cipher, dek_id, version = crypto.encrypt_account_credentials(PLAIN_AK, PLAIN_SK)
    assert dek_id and version == crypto.CURRENT_KEY_VERSION
    ak, sk = crypto.decrypt_account_credentials(
        ak_cipher, sk_cipher, dek_id=dek_id, key_version=version
    )
    assert (ak, sk) == (PLAIN_AK, PLAIN_SK)
