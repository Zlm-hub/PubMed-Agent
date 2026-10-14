"""访问防护测试（2026-10-14 面向真实运营加固）。

运行：backend/.venv/Scripts/python.exe scripts/test_guard.py

覆盖四道防护 + 一个不变量：
  1. 登录 cookie 必须带 HttpOnly（XSS 也偷不走登录态）；
  2. 登录失败锁定：达上限后返回 429，且**锁定期间正确密码也不放行**（证明没有继续跑 PBKDF2）；
     窗口过期后恢复；成功登录会清零计数；
  3. 接口速率限制：按 IP 计数，`/api/health` 豁免（监控探活不能被限流）；
  4. 分析端点单列更严的额度；
  5. 自助注册限流（挡「批量注册刷试用额度」），但首引导那次不受限；
  6. 全部置 0 时完全关闭（行为回到加固前）。
"""
import os
import sys
import tempfile
from pathlib import Path

TMP = Path(tempfile.mkdtemp(prefix="pa_guard_test_"))
os.environ["ACCESS_CODE"] = ""
os.environ["FRONTEND_DIST"] = str(TMP / "no-dist")

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from fastapi.testclient import TestClient  # noqa: E402
from app import cache, config, guard  # noqa: E402
from app import main as appmain  # noqa: E402
from app import userdb  # noqa: E402

PASS = 0


def check(name: str, cond: bool) -> None:
    global PASS
    print(f"[{'PASS' if cond else 'FAIL'}] {name}")
    if not cond:
        sys.exit(1)
    PASS += 1


def apply(**kw) -> None:
    """改配置并让限流器立刻生效（测试里反复用到）。"""
    for k, v in kw.items():
        setattr(config, k, v)
    guard.setup()
    for lim in (guard.login_fail, guard.api_rate, guard.analyze_rate, guard.register_rate):
        lim.clear()


def seed_cache(query: str) -> None:
    key = cache.cache_key(query, 200, True)
    appmain._cache[key] = {
        "query": query, "total": 5, "returned": 5, "trace": [], "articles": [],
        "wordcloud": [], "top100": [], "years": [], "journals": [],
        "review": {"text": "（测试）", "mock": True},
    }


config.ALLOW_REGISTRATION = True
config.WORD_ZH = False
config.FREE_TRIAL_LIMIT = 0  # 额度单独由 test_trial_limit 覆盖，这里只测防护

userdb.DB_PATH = str(TMP / "users.db")
with TestClient(appmain.app) as c:
    # ---------- 1) HttpOnly ----------
    apply(LOGIN_MAX_FAILS=0, RATE_LIMIT_PER_MIN=0, ANALYZE_RATE_PER_MIN=0, REGISTER_PER_DAY=0)
    r = c.post("/api/auth/register", json={"username": "guard1", "password": "guard123456"})
    check("注册成功（首引导/普通注册）", r.status_code == 200)
    sc = r.headers.get("set-cookie", "")
    check("登录 cookie 带 HttpOnly", "HttpOnly" in sc)
    check("登录 cookie 带 SameSite=Lax", "samesite=lax" in sc.lower())

    # ---------- 2) 登录失败锁定 ----------
    apply(LOGIN_MAX_FAILS=3, LOGIN_LOCK_SECONDS=60)
    bad = {"username": "guard1", "password": "wrong-pass"}
    codes = [c.post("/api/auth", json=bad).status_code for _ in range(3)]
    check(f"前 3 次失败均 401（实际 {codes}）", codes == [401, 401, 401])
    r4 = c.post("/api/auth", json=bad)
    check("第 4 次失败被锁定为 429", r4.status_code == 429)
    check("429 带 Retry-After 头", bool(r4.headers.get("retry-after")))
    r5 = c.post("/api/auth", json={"username": "guard1", "password": "guard123456"})
    check("锁定期间**正确密码也被拒**（不跑 PBKDF2，防爆破算力放大）", r5.status_code == 429)

    # 窗口过期 → 恢复；且成功登录会清零计数
    # （阈值与窗口都现读 config，所以这里改 config 即可，无需重启或重建限流器）
    config.LOGIN_LOCK_SECONDS = 0  # 窗口归零 = 计数立刻失效
    check("锁定窗口过期后可正常登录", c.post("/api/auth", json={"username": "guard1", "password": "guard123456"}).status_code == 200)
    config.LOGIN_LOCK_SECONDS = 300
    c.post("/api/auth", json=bad)
    c.post("/api/auth", json=bad)
    check("成功登录清零计数（2 次失败后仍能登录）",
          c.post("/api/auth", json={"username": "guard1", "password": "guard123456"}).status_code == 200)

    # ---------- 3) 接口速率限制 + health 豁免 ----------
    apply(RATE_LIMIT_PER_MIN=3)
    codes = [c.get("/api/auth").status_code for _ in range(3)]
    check(f"限 3 次/分：前 3 次放行（实际 {codes}）", codes == [200, 200, 200])
    r = c.get("/api/auth")
    check("第 4 次 429", r.status_code == 429)
    check("429 提示含重试秒数", "秒后重试" in r.json().get("detail", ""))
    hp = [c.get("/api/health").status_code for _ in range(6)]
    check(f"health 豁免限流（连续 6 次均 200，实际 {hp}）", hp == [200] * 6)

    # ---------- 4) 分析端点单列额度 ----------
    apply(RATE_LIMIT_PER_MIN=0, ANALYZE_RATE_PER_MIN=2)
    c.post("/api/auth", json={"username": "guard1", "password": "guard123456"})
    seed_cache("guardq")
    body = {"query": "guardq", "max_results": 200, "include_review": True}
    a1 = c.post("/api/analyze", json=body).status_code
    a2 = c.post("/api/analyze", json=body).status_code
    a3 = c.post("/api/analyze", json=body).status_code
    check(f"分析限 2 次/分：前两次放行、第三次 429（实际 {a1}/{a2}/{a3}）", (a1, a2, a3) == (200, 200, 429))
    s = c.get("/api/analyze/stream", params={"query": "guardq", "max_results": 200})
    check("流式端点同受分析额度限制（429）", s.status_code == 429)

    # ---------- 5) 注册限流 ----------
    apply(REGISTER_PER_DAY=2)
    r1 = c.post("/api/auth/register", json={"username": "reg1", "password": "reg123456"})
    r2 = c.post("/api/auth/register", json={"username": "reg2", "password": "reg123456"})
    r3 = c.post("/api/auth/register", json={"username": "reg3", "password": "reg123456"})
    check(f"注册限 2 个/天：前两个成功、第三个 429（实际 {r1.status_code}/{r2.status_code}/{r3.status_code}）",
          (r1.status_code, r2.status_code, r3.status_code) == (200, 200, 429))
    check("注册 429 提示引导联系管理员", "管理员" in r3.json().get("detail", ""))

    # ---------- 6) 全部关闭时行为回到加固前 ----------
    apply(LOGIN_MAX_FAILS=0, RATE_LIMIT_PER_MIN=0, ANALYZE_RATE_PER_MIN=0, REGISTER_PER_DAY=0)
    codes = [c.post("/api/auth", json=bad).status_code for _ in range(5)]
    check(f"关闭锁定：连续 5 次失败仍是 401（实际 {codes}）", codes == [401] * 5)
    codes = [c.get("/api/auth").status_code for _ in range(8)]
    check("关闭限流：连续 8 次请求全部放行", codes == [200] * 8)

print(f"\n全部 {PASS} 项通过，临时库：{TMP}")
