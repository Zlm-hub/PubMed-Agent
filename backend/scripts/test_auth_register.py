"""自助注册开关与首引导场景测试。

运行：backend/.venv/Scripts/python.exe scripts/test_auth_register.py

覆盖三种部署形态下的注册行为（闸门模式自动切换是本次设计的核心，必须逐一验证）：
  1. ALLOW_REGISTRATION=0 + 已配 ADMIN_*  → 注册 403，管理员建号（默认形态）
  2. ALLOW_REGISTRATION=1 + 已配 ADMIN_*  → 登录页可注册，注册者恒为 user
  3. ALLOW_REGISTRATION=1 + 无 ADMIN_*   → 首引导：第一个注册者成为 admin，之后只能注册 user
"""
import os
import sys
import tempfile
from pathlib import Path

TMP = Path(tempfile.mkdtemp(prefix="pa_reg_test_"))
os.environ["ACCESS_CODE"] = ""
os.environ["FRONTEND_DIST"] = str(TMP / "no-dist")

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from fastapi.testclient import TestClient  # noqa: E402
from app import config  # noqa: E402
from app import main as appmain  # noqa: E402
from app import userdb  # noqa: E402

# 本套测试关注的是注册与首引导语义，**不测访问防护**：这里显式关掉限流与登录锁定，
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
    """每场景一套独立临时库（用户库换代 ≈ 换一套部署）。"""
    userdb.DB_PATH = str(TMP / name)
    return TestClient(appmain.app)


# 场景 1：注册关闭 + 管理员由 env 建 → 403，且 /api/auth 告知前端不显示注册入口
os.environ["ADMIN_USERNAME"] = "admin"
os.environ["ADMIN_PASSWORD"] = "admin123"
config.ADMIN_USERNAME, config.ADMIN_PASSWORD = "admin", "admin123"
config.ALLOW_REGISTRATION = False
with fresh("users_off.db") as c1:
    st = c1.get("/api/auth").json()
    check("关闭态：auth 告知不允许注册", st["allow_registration"] is False)
    check("关闭态：can_bootstrap 为假", st["can_bootstrap"] is False)
    r = c1.post("/api/auth/register", json={"username": "eve", "password": "eve123456"})
    check("关闭态：注册 403", r.status_code == 403)
    check("关闭态：管理员仍可登录", c1.post("/api/auth", json={"username": "admin", "password": "admin123"}).status_code == 200)
    check("关闭态：库里只有管理员", userdb.count() == 1)

# 场景 2：注册开启 + 已有管理员 → 注册者恒为 user
config.ALLOW_REGISTRATION = True
with fresh("users_on.db") as c2:
    st = c2.get("/api/auth").json()
    check("开启态：auth 告知允许注册", st["allow_registration"] is True)
    check("开启态：有管理员时 can_bootstrap 为假", st["can_bootstrap"] is False)
    r = c2.post("/api/auth/register", json={"username": "frank", "password": "frank123456"})
    check("开启态：注册成功", r.status_code == 200 and r.json()["bootstrap"] is False)
    check("开启态：注册者为普通用户", userdb.get_by_username("frank")["role"] == "user")
    check("开启态：注册即登录", c2.get("/api/sessions").status_code == 200)

    # 注册写入 source（追溯"从哪注册的"）——必须在切库前查，DB_PATH 是模块级变量
    frank = userdb.get_by_username("frank")
    check("注册账号记录了来源 source", bool((frank or {}).get("source")))

# 场景 3：注册开启且无任何账号 → 首引导（第一个注册者即管理员）
config.ADMIN_USERNAME, config.ADMIN_PASSWORD = "", ""
with fresh("users_boot.db") as c3:
    st = c3.get("/api/auth").json()
    check("首引导：can_bootstrap 为真", st["can_bootstrap"] is True)
    r = c3.post("/api/auth/register", json={"username": "root1", "password": "root123456"})
    check("首引导：第一个注册者成为管理员", r.status_code == 200 and r.json()["user"]["role"] == "admin")
    check("首引导：bootstrap 标记为真", r.json()["bootstrap"] is True)
    r = c3.post("/api/auth/register", json={"username": "second", "password": "second12345"})
    check("首引导之后：注册者回归普通用户", r.status_code == 200 and r.json()["user"]["role"] == "user")
    check("首引导之后：can_bootstrap 转假", c3.get("/api/auth").json()["can_bootstrap"] is False)

print(f"\n全部 {PASS} 项通过，临时库：{TMP}")
