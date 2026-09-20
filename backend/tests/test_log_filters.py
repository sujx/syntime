import logging

from common.log_filters import SensitiveDataFilter, sanitize


def _record(msg, args=None) -> logging.LogRecord:
    return logging.LogRecord(
        name="test", level=logging.INFO, pathname="p", lineno=1, msg=msg, args=args, exc_info=None
    )


def test_mask_aliyun_ak():
    assert sanitize("AK=LTAI5tFakeAK123456 同步失败") == "AK=*** 同步失败"


def test_mask_other_vendor_ak_prefix():
    out = sanitize("credential AKIDfaker12345678")
    assert "faker12345678" not in out
    assert "AKID***" in out


def test_mask_sk_and_password_kv():
    assert sanitize("sk=ZjFkZTAxMDEwMDA3") == "sk=***"
    assert sanitize("password: hunter2secret") == "password: ***"
    assert sanitize('"secret_key": "abc12345678"') == '"secret_key": "***"'


def test_mask_jwt_token():
    token = "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJ1c2VyX2lkIjoxfQ.s1gnAtUr3"
    out = sanitize(f"Authorization: Bearer {token}")
    assert token not in out
    assert "eyJ***JWT" in out


def test_normal_message_untouched():
    msg = "账单同步完成 insert=100 update=2 account=aliyun/main"
    assert sanitize(msg) == msg


def test_filter_masks_message_and_clears_args():
    record = _record("access_key=LTAI5tFakeAK123456 count=%s", (42,))
    assert SensitiveDataFilter().filter(record) is True
    assert record.getMessage() == "access_key=*** count=42"


def test_filter_masks_exc_text():
    record = _record("boom")
    record.exc_text = 'ValueError: invalid sk=abc123456789'
    SensitiveDataFilter().filter(record)
    assert "abc123456789" not in (record.exc_text or "")
