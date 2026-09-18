"""全链路监控日志（设计见 docs/监控日志设计方案.md）。

目标：后端每一步（改写/检索/取回/匹配/聚合/综述/落库）都落一条结构化日志，
一次请求用 request_id 串起来——排障时报这个码即可回放全程。

设计约束：
  - 标准库 logging 零新依赖；按天轮转双文件（app 留 14 天 / error 留 30 天）
  - request_id 用 contextvars 透传，各模块函数签名零改动
  - 全部 best-effort：日志自身任何故障静默降级，绝不影响主链路
  - 脱敏：敏感字段（key/token/email）的值统一打码，密钥永不落日志
"""
from __future__ import annotations

import json
import logging
import logging.handlers
import os
import re
import secrets
from contextvars import ContextVar

_request_id: ContextVar[str] = ContextVar("request_id", default="-")

_configured = False
logger = logging.getLogger("monitor")

LOG_DIR_DEFAULT = os.path.normpath(os.path.join(os.path.dirname(__file__), "..", "logs"))

# 敏感字段值打码（key/token/email/password=后面跟的非空白一律替换）
_SENSITIVE_RE = re.compile(
    r"((?:api_?key|token|email|password)[\"']?\s*[:=]\s*)(\"[^\"]*\"|\S+)", re.I
)


def set_request_id(rid: str | None = None) -> str:
    """入口处生成并绑定本次请求的短码；返回可直接放进响应体的 id。"""
    rid = rid or secrets.token_hex(3)
    _request_id.set(rid)
    return rid


def get_request_id() -> str:
    return _request_id.get()


def _scrub(text: str) -> str:
    return _SENSITIVE_RE.sub(r"\1***", text)


class _ContextFilter(logging.Filter):
    """给每条记录注入 request_id 并做敏感值打码。"""

    def filter(self, record: logging.LogRecord) -> bool:
        record.rid = _request_id.get()
        if isinstance(record.msg, str):
            record.msg = _scrub(record.msg)
        for i, a in enumerate(record.args or ()):
            if isinstance(a, str):
                record.args = (*record.args[:i], _scrub(a), *record.args[i + 1 :])
        return True


class _AccessNoiseFilter(logging.Filter):
    """uvicorn access log 降噪（决策 D4）：只放行 /api/analyze，health 等全部丢弃。"""

    def filter(self, record: logging.LogRecord) -> bool:
        try:
            return "/api/analyze" in record.getMessage()
        except Exception:  # noqa: BLE001
            return True


def setup(
    level: str = "INFO",
    log_dir: str | None = None,
    retention_app: int = 14,
    retention_error: int = 30,
) -> None:
    """初始化双文件日志。重复调用/失败均静默，保证只配置一次且不影响主链路。"""
    global _configured
    if _configured:
        return
    try:
        d = log_dir or LOG_DIR_DEFAULT
        os.makedirs(d, exist_ok=True)
        fmt = logging.Formatter(
            "%(asctime)s | %(levelname)-7s | %(rid)s | %(message)s",
            "%Y-%m-%d %H:%M:%S",
        )

        def _attach(handler: logging.Handler, lvl: int) -> None:
            handler.setLevel(lvl)
            handler.setFormatter(fmt)
            handler.addFilter(_ContextFilter())
            logger.addHandler(handler)

        app_h = logging.handlers.TimedRotatingFileHandler(
            os.path.join(d, "app.log"), when="midnight", backupCount=retention_app,
            encoding="utf-8",
        )
        _attach(app_h, logging.INFO)
        err_h = logging.handlers.TimedRotatingFileHandler(
            os.path.join(d, "error.log"), when="midnight", backupCount=retention_error,
            encoding="utf-8",
        )
        _attach(err_h, logging.ERROR)

        logger.setLevel(getattr(logging, level.upper(), logging.INFO))
        logger.propagate = False

        # uvicorn access log 降噪：只留 /api/analyze（决策 D4）
        logging.getLogger("uvicorn.access").addFilter(_AccessNoiseFilter())

        _configured = True
    except Exception:  # noqa: BLE001
        pass  # 日志器建不起来也绝不影响主链路


def step(module: str, event: str, *, ok: bool = True, ms: float | None = None,
         exc: bool = False, **fields) -> None:
    """记一步。ok=False 时落 ERROR（并按 exc 决定是否带堆栈）；否则 INFO。

    用法：monitor.step("pubmed", "esearch.done", ms=120, term="ALS", total=73174)
    任意字段都会进详情 JSON；None 值自动省略。
    """
    if not _configured:
        return
    detail = {k: v for k, v in fields.items() if v is not None}
    if ms is not None:
        detail["ms"] = round(ms)
    try:
        payload = json.dumps(detail, ensure_ascii=False, default=str)
    except Exception:  # noqa: BLE001
        payload = str(detail)
    msg = f"{module}.{event} | {payload}"
    if ok:
        logger.info(msg)
    else:
        logger.error(msg, exc_info=exc)


def warning(module: str, event: str, **fields) -> None:
    """记一条 WARNING——专用于「失败但已兜底、不影响主链路」的场景。"""
    if not _configured:
        return
    detail = {k: v for k, v in fields.items() if v is not None}
    try:
        payload = json.dumps(detail, ensure_ascii=False, default=str)
    except Exception:  # noqa: BLE001
        payload = str(detail)
    logger.warning(f"{module}.{event} | {payload}")
