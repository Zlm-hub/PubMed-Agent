"""访问防护：登录失败锁定 + 按 IP 速率限制（2026-10-14 面向真实运营加固）。

**为什么用进程内滑动窗口**：目标是挡住「撞库」与「单 IP 刷爆上游额度」，这类风控不需要
跨重启的精确计数；本服务是单容器单 worker（2 核 2G 小机器），内存实现零依赖、零运维。
接口面刻意保持极窄（`hit` / `retry_after` / `reset` / `sweep`）—— 将来要多实例时，
只把这一个文件换成 Redis 实现即可，调用方不用动。

**已知边界（如实声明）**：
  - 计数不跨进程、不跨重启 → **多实例部署会各自计数**（届时必须换共享存储）；
  - 按 IP 计数会把同一 NAT 出口的多个用户合并计量，阈值要留余量；
  - 攻击者换 IP 即可绕过 —— 真正的兜底是「按账号计的试用额度」；
  - `sweep()` 由调用方定期触发（本项目挂在每次请求的轻量位置，控制键数量上限）。
"""
from __future__ import annotations

import threading
import time
from collections import deque
from typing import Callable


class SlidingWindow:
    """滑动窗口计数器：`window` 秒内最多 `limit` 次。线程安全。

    阈值与窗口都支持**传函数**（延迟求值）——这样阈值直接从 config 现读，
    运维改配置或管理端临时关闭防护后立刻生效，不需要重启、也不用重新 setup()。
    `limit <= 0` 表示不限制。
    """

    def __init__(self, limit: int | Callable[[], int] = 0,
                 window: float | Callable[[], float] = 60.0) -> None:
        self._limit = limit
        self._window = window
        self._hits: dict[str, deque[float]] = {}
        self._lock = threading.Lock()

    # ---- 阈值：常量或现读函数 ----
    @property
    def limit(self) -> int:
        return int(self._limit() if callable(self._limit) else self._limit)

    @limit.setter
    def limit(self, value: int) -> None:
        self._limit = value

    @property
    def window(self) -> float:
        return float(self._window() if callable(self._window) else self._window)

    @window.setter
    def window(self, value: float) -> None:
        self._window = value

    # ---- 内部 ----
    def _prune(self, key: str, now: float) -> deque[float]:
        q = self._hits.get(key)
        if q is None:
            q = deque()
            self._hits[key] = q
        cutoff = now - self.window
        while q and q[0] <= cutoff:
            q.popleft()
        return q

    # ---- 对外的四个动作 ----
    def hit(self, key: str) -> tuple[bool, int]:
        """记一次并判断是否放行，返回 `(allowed, retry_after_seconds)`。"""
        limit = self.limit
        if limit <= 0:
            return True, 0
        now = time.monotonic()
        with self._lock:
            q = self._prune(key, now)
            if len(q) >= limit:
                return False, max(1, int(self.window - (now - q[0])) + 1)
            q.append(now)
            return True, 0

    def retry_after(self, key: str) -> int:
        """只查不记：已触发限制时返回剩余秒数，否则 0（登录前置检查用它）。"""
        limit = self.limit
        if limit <= 0:
            return 0
        now = time.monotonic()
        with self._lock:
            q = self._prune(key, now)
            if len(q) >= limit:
                return max(1, int(self.window - (now - q[0])) + 1)
            return 0

    def reset(self, key: str) -> None:
        """清零某个键（登录成功、管理员解锁时用）。"""
        with self._lock:
            self._hits.pop(key, None)

    def clear(self) -> None:
        """清空全部计数（测试用；运维「解锁所有」也可调）。"""
        with self._lock:
            self._hits.clear()

    def sweep(self, keep_at_most: int = 5000) -> None:
        """清理过期/空键并限制键总数，防止长期运行内存无界增长。"""
        now = time.monotonic()
        with self._lock:
            for k in list(self._hits):
                if not self._prune(k, now):
                    self._hits.pop(k, None)
            if len(self._hits) > keep_at_most:
                for k in list(self._hits)[: len(self._hits) - keep_at_most]:
                    self._hits.pop(k, None)


# ---- 全局实例：阈值直接现读 config（改配置立刻生效，无需重启或重新 setup）----
#   login_fail    : 同一 IP+用户名 在窗口内失败次数 → 冷却
#   api_rate      : 每 IP 每分钟的接口调用上限（health 除外）
#   analyze_rate  : 每 IP 每分钟的分析调用上限（最贵的那两个端点）
#   register_rate : 每 IP 每天的自助注册账号数（挡「批量注册刷试用额度」）
def _cfg(name: str, default: int = 0):
    """延迟读取 config 里的整数配置（config 的 import 放函数内，避免循环依赖）。"""
    def _get() -> int:
        from . import config

        return int(getattr(config, name, default) or 0)

    return _get


login_fail = SlidingWindow(_cfg("LOGIN_MAX_FAILS"), _cfg("LOGIN_LOCK_SECONDS", 300))
api_rate = SlidingWindow(_cfg("RATE_LIMIT_PER_MIN"), 60.0)
analyze_rate = SlidingWindow(_cfg("ANALYZE_RATE_PER_MIN"), 60.0)
register_rate = SlidingWindow(_cfg("REGISTER_PER_DAY"), 86400.0)


def setup() -> None:
    """兼容保留：阈值已改为现读配置，这里只需清掉历史计数（幂等）。"""
    for lim in (login_fail, api_rate, analyze_rate, register_rate):
        lim.clear()


def client_ip(request) -> str:
    """来源标识。容器部署在 nginx 之后时优先取 `X-Forwarded-For` 首个地址。"""
    xff = request.headers.get("x-forwarded-for", "")
    if xff:
        return xff.split(",")[0].strip()
    return request.client.host if request.client else "unknown"
