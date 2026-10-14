"""免费试用额度测试（2026-09-21 服务器版「每个账号免费试用 3 次」）。

运行：backend/.venv/Scripts/python.exe scripts/test_trial_limit.py

要点：
  - 额度未启用（FREE_TRIAL_LIMIT=0）时行为与旧版完全一致，一次都不计数；
  - 普通账号第 1~3 次放行、第 4 次 403，提示里带管理员联系方式；
  - 管理员账号豁免（不计数、不受限）；open 模式（无身份）同样不受限；
  - SSE 端点超限时回 error 事件（EventSource 读不到 403 响应体，只能走事件）；
  - 管理员可重置计数（客户联系后再给次数）。

测试**不触网**：分析结果预置进内存缓存，走的都是缓存命中分支；
缓存命中仍然计次是刻意设计（否则换词/清缓存就能绕过限制）。
"""
import os
import sys
import tempfile
from pathlib import Path

TMP = Path(tempfile.mkdtemp(prefix="pa_trial_test_"))
os.environ["ACCESS_CODE"] = ""
os.environ["FRONTEND_DIST"] = str(TMP / "no-dist")

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from fastapi.testclient import TestClient  # noqa: E402
from app import cache, config  # noqa: E402
from app import config  # noqa: E402
from app import main as appmain  # noqa: E402
from app import userdb  # noqa: E402

# 本套测试关注的是试用额度语义，**不测访问防护**：这里显式关掉限流与登录锁定，
# 避免"注册满 3 个账号被 429""失败次数超限被锁"这类相互干扰（防护单独由
# scripts/test_guard.py 覆盖）。
from app import guard as _guard  # noqa: E402

config.LOGIN_MAX_FAILS = 0
config.LOGIN_LOCK_SECONDS = 300
config.RATE_LIMIT_PER_MIN = 0
config.ANALYZE_RATE_PER_MIN = 0
config.REGISTER_PER_DAY = 0
_guard.setup()


PASS = 0


def check(name: str, cond: bool) -> None:
    global PASS
    print(f"[{'PASS' if cond else 'FAIL'}] {name}")
    if not cond:
        sys.exit(1)
    PASS += 1


def fresh(name: str) -> TestClient:
    userdb.DB_PATH = str(TMP / name)
    return TestClient(appmain.app)


def seed_cache(query: str, max_results: int = 200) -> None:
    """把结果预置进内存缓存，让 /api/analyze 走缓存分支（测试不触网）。"""
    key = cache.cache_key(query, max_results, True)
    appmain._cache[key] = {
        "query": query, "total": 12, "returned": 12, "trace": [],
        "articles": [], "wordcloud": [], "top100": [], "years": [], "journals": [],
        "review": {"text": "（测试用综述）", "mock": True},
    }


def analyze(c: TestClient, query: str):
    return c.post("/api/analyze", json={"query": query, "max_results": 200, "include_review": True})


config.ADMIN_USERNAME, config.ADMIN_PASSWORD = "admin", "admin123"
config.ALLOW_REGISTRATION = True
config.WORD_ZH = False  # 关掉机翻，避免测试触网
seed_cache("trialq")

# ---------- 场景 1：额度未启用（本地默认）→ 完全不限、不计数 ----------
config.FREE_TRIAL_LIMIT = 0
config.ADMIN_CONTACT = "QQ3184331768"
with fresh("users_off.db") as c1:
    c1.post("/api/auth", json={"username": "admin", "password": "admin123"})
    c1.post("/api/auth/register", json={"username": "bob", "password": "bob123456"})
    codes = [analyze(c1, "trialq").status_code for _ in range(4)]
    check("未启用额度：普通用户连续 4 次全部放行", codes == [200, 200, 200, 200])
    check("未启用额度：不计数（trial_used 保持 0）", userdb.trial_used_of(userdb.get_by_username("bob")["id"]) == 0)
    check("未启用额度：/api/trial 告知未启用", c1.get("/api/trial").json()["enabled"] is False)

# ---------- 场景 2：额度 = 3（服务器形态） ----------
config.FREE_TRIAL_LIMIT = 3
with fresh("users_3.db") as c2:
    c2.post("/api/auth", json={"username": "admin", "password": "admin123"})
    # 先以管理员身份看额度（GET /api/auth 看的是当前 cookie 的身份）
    check("管理员：/api/auth 额度为 None（豁免）", c2.get("/api/auth").json()["trial"] is None)
    c2.post("/api/auth/register", json={"username": "carol", "password": "carol12345"})
    carol = userdb.get_by_username("carol")

    check("普通用户：登录后 /api/auth 返回额度（3 次）",
          c2.get("/api/auth").json()["trial"]["limit"] == 3)

    check("第 1 次放行", analyze(c2, "trialq").status_code == 200)
    check("第 2 次放行", analyze(c2, "trialq").status_code == 200)
    r3 = analyze(c2, "trialq")
    check("第 3 次放行（正好用满）", r3.status_code == 200)
    check("用满后计数 = 3", userdb.trial_used_of(carol["id"]) == 3)

    r4 = analyze(c2, "trialq")
    check("第 4 次被拒（403）", r4.status_code == 403)
    detail = r4.json().get("detail", "")
    check("拒绝提示含「免费试用次数已用完」", "免费试用次数已用完" in detail)
    check("拒绝提示含管理员联系方式 QQ3184331768", "QQ3184331768" in detail)
    check("被拒不再计数", userdb.trial_used_of(carol["id"]) == 3)

    # SSE：EventSource 读不到 403 响应体，必须回 error 事件
    s = c2.get("/api/analyze/stream", params={"query": "trialq", "max_results": 200})
    check("SSE 超限：HTTP 仍是 200（事件通道）", s.status_code == 200)
    check("SSE 超限：回 error 事件且带 trial_limit 标记",
          '"type": "error"' in s.text and "trial_limit" in s.text)
    check("SSE 超限：事件里带联系方式", "QQ3184331768" in s.text)

    # /api/trial 快照
    tj = c2.get("/api/trial").json()
    check("/api/trial 显示剩余 0 次", tj["quota"]["remaining"] == 0 and tj["quota"]["used"] == 3)

    # 管理员重置 → 又能用
    adm = c2.post("/api/auth", json={"username": "admin", "password": "admin123"})
    check("管理员登录", adm.status_code == 200)
    patch = c2.patch(f"/api/admin/users/{carol['id']}", json={"reset_trial": True})
    check("管理员重置试用计数成功", patch.status_code == 200 and patch.json()["trial_used"] == 0)
    # 切回 carol 身份（上一步是管理员 cookie，管理员豁免不计数）
    check("carol 重新登录", c2.post("/api/auth", json={"username": "carol", "password": "carol12345"}).status_code == 200)
    check("重置后普通用户可再次分析", analyze(c2, "trialq").status_code == 200)
    check("重置后计数重新累加", userdb.trial_used_of(carol["id"]) == 1)

    # 管理员自己连续 5 次都不受限
    c2.post("/api/auth", json={"username": "admin", "password": "admin123"})
    admin_codes = [analyze(c2, "trialq").status_code for _ in range(5)]
    check("管理员 5 次全部放行", admin_codes == [200] * 5)
    check("管理员不计数", userdb.trial_used_of(userdb.get_by_username("admin")["id"]) == 0)

# ---------- 场景 3：额度 = 1 的边界 ----------
config.FREE_TRIAL_LIMIT = 1
with fresh("users_1.db") as c3:
    c3.post("/api/auth", json={"username": "admin", "password": "admin123"})
    c3.post("/api/auth/register", json={"username": "dave", "password": "dave123456"})
    check("额度 1：第 1 次放行", analyze(c3, "trialq").status_code == 200)
    check("额度 1：第 2 次被拒", analyze(c3, "trialq").status_code == 403)

# ---------- 场景 4：open 模式（无身份）不受额度影响 ----------
config.FREE_TRIAL_LIMIT = 3
config.ADMIN_USERNAME, config.ADMIN_PASSWORD = "", ""
with fresh("users_open.db") as c4:
    check("open 模式：无身份放行（额度不适用）", analyze(c4, "trialq").status_code == 200)

print(f"\n全部 {PASS} 项通过，临时库：{TMP}")
