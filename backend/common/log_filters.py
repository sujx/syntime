"""日志脱敏（PRD 4.5-3、backend-ops.md 模块五）：AK/SK、token、签名串禁止入日志。

以 logging.Filter 形式挂在 LOGGING 的 handler 上，对消息与异常堆栈文本做正则掩码。
"""

import logging
import re

# 阿里云 AccessKey ID（LTAI 前缀）与其他厂商长凭证
_AK_PATTERN = re.compile(r"\b(?:LTAI|AKLT|AKID)[0-9A-Za-z]{4,}")
# JWT（simplejwt 签发的 access/refresh token）
_JWT_PATTERN = re.compile(r"eyJ[A-Za-z0-9_-]{8,}\.[A-Za-z0-9_-]{4,}\.[A-Za-z0-9_-]{4,}")
# 键值形态的敏感项：access_key / secret_key / ak / sk / password / token / signature…
_KV_PATTERN = re.compile(
    r"(?i)\b("
    r"access[_-]?key(?:[_-]?id)?|access[_-]?key[_-]?secret|secret[_-]?access[_-]?key|"
    r"secret[_-]?key|sk|ak|password|passwd|token|signature|signature[_-]?nonce|"
    r"authorization"
    r")([\"']?\s*[:=]\s*[\"']?)[A-Za-z0-9_\-+/=.%@:]{6,}"
)
_KV_REPL = r"\1\2***"


def sanitize(text: str) -> str:
    """对文本做脱敏替换，返回新字符串。"""
    text = _KV_PATTERN.sub(_KV_REPL, text)
    text = _AK_PATTERN.sub(lambda m: m.group(0)[:4] + "***", text)
    return _JWT_PATTERN.sub("eyJ***JWT", text)


class SensitiveDataFilter(logging.Filter):
    """挂接在 handler 上：掩码 record 的消息（含 args 展开）与异常堆栈文本。"""

    def filter(self, record: logging.LogRecord) -> bool:
        record.msg = sanitize(record.getMessage())
        record.args = None
        if record.exc_text:
            record.exc_text = sanitize(record.exc_text)
        return True
