"""HTTP 层端到端鉴权测试（进程内 TestClient，不占端口、不碰真实数据）。

运行：backend/.venv/Scripts/python.exe scripts/test_http_auth.py
覆盖：存量划归 → 未登录 401 → 登录/登出 → 双用户隔离（HTTP 语义）→
      admin 接口 403/200 → 禁用即时踢出 → 保护规则 → open 模式回退。
"""
import os
import sys
import tempfile
from pathlib import Path

TMP = Path(tempfile.mkdtemp(prefix="pa_http_test_"))
os.environ["ADMIN_USERNAME"] = "admin"
os.environ["ADMIN_PASSWORD"] = "admin123"
os.environ["ACCESS_CODE"] = ""
os.environ["ALLOW_REGISTRATION"] = "1"  # 本套覆盖注册；注册的关闭态与首引导见 test_auth_register.py
os.environ["FRONTEND_DIST"] = str(TMP / "no-dist")  # 不挂 SPA 静态目录

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from fastapi.testclient import TestClient  # noqa: E402

from app import main as appmain  # noqa: E402
from app import sessiondb, userdb  # noqa: E402

userdb.DB_PATH = str(TMP / "users.db")
sessiondb.DB_PATH = str(TMP / "sessions.db")

PASS = 0


def check(name: str, cond: bool) -> None:
    global PASS
    print(f"[{'PASS' if cond else 'FAIL'}] {name}")
    if not cond:
        sys.exit(1)
    PASS += 1


FAKE_RESULT = {"query": "x", "total": 0, "returned": 0, "stats": {"if_statistics": {"known_count": 0}}}

# 0) startup 之前直写一条无归属会话（模拟升级前的存量数据）
legacy = sessiondb.create_thread("legacy", FAKE_RESULT, title="存量会话")
check("存量会话归属为 NULL", legacy["user_id"] is None)

with TestClient(appmain.app) as client:  # with 语句触发 startup（bootstrap + 划归）
    check("startup 建 admin", userdb.count() == 1)
    admin = userdb.get_by_username("admin")
    check("存量会话划归 admin", sessiondb.get_thread(legacy["id"])["user_id"] == admin["id"])

    # 1) 用户体系激活后：未登录一律 401
    check("未登录列表 401", client.get("/api/sessions").status_code == 401)
    check("未登录写会话 401", client.post("/api/sessions", json={"kind": "chat", "query": "q", "result": FAKE_RESULT}).status_code == 401)
    check("未登录管理接口 401", client.get("/api/admin/users").status_code == 401)

    # 2) 登录
    check("错误密码 401", client.post("/api/auth", json={"username": "admin", "password": "wrong"}).status_code == 401)
    r = client.post("/api/auth", json={"username": "admin", "password": "admin123"})
    check("admin 登录成功", r.status_code == 200 and r.json()["user"]["role"] == "admin")
    check("下发登录 cookie", "pa_session" in client.cookies)

    r = client.get("/api/auth")
    check("状态接口返回用户", r.json()["authorized"] is True and r.json()["user"]["username"] == "admin")
    r = client.get("/api/sessions")
    check("admin 侧栏见划归的旧会话", [s["id"] for s in r.json()["sessions"]] == [legacy["id"]])

    # 3) admin 建 bob；bob 登录（第二客户端 = 第二浏览器）
    check("admin 建号 bob", client.post("/api/admin/users", json={"username": "bob", "password": "bob123456"}).status_code == 200)

    bob_client = TestClient(appmain.app)
    check("bob 登录成功", bob_client.post("/api/auth", json={"username": "bob", "password": "bob123456"}).status_code == 200)
    check("bob 侧栏初始为空", bob_client.get("/api/sessions").json()["sessions"] == [])

    # 4) bob 建自己的会话；对 admin 的会话读写全被拒
    r = bob_client.post("/api/sessions", json={"kind": "chat", "query": "bob topic", "result": FAKE_RESULT})
    bob_sid = r.json()["id"]
    check("bob 建会话归 bob", r.json()["user_id"] == userdb.get_by_username("bob")["id"])
    check("bob 看 admin 会话详情 404", bob_client.get(f"/api/sessions/{legacy['id']}").status_code == 404)
    check("bob 追问 admin 线程 404", bob_client.post(f"/api/sessions/{legacy['id']}/messages", json={"query": "q", "result": FAKE_RESULT}).status_code == 404)
    check("bob 删 admin 会话无效", bob_client.delete(f"/api/sessions/{legacy['id']}").json()["deleted"] is False)
    check("admin 侧栏看不到 bob 会话", bob_sid not in [s["id"] for s in client.get("/api/sessions").json()["sessions"]])

    # 5) 管理接口权限
    check("bob 访问管理接口 403", bob_client.get("/api/admin/users").status_code == 403)
    r = client.get("/api/admin/overview")
    check("admin 总览 200", r.status_code == 200)
    per = {u["username"]: u for u in r.json()["per_user"]}
    check("总览统计正确", per["admin"]["chats"] == 1 and per["bob"]["chats"] == 1)
    r = client.get("/api/admin/sessions")
    check("admin 全局视图含双方", {s["id"] for s in r.json()["sessions"]} == {legacy["id"], bob_sid})
    r = client.get("/api/admin/sessions", params={"user_id": per["bob"]["id"]})
    check("admin 按用户过滤", [s["id"] for s in r.json()["sessions"]] == [bob_sid])

    # 6) 侧栏「清空」只清自己；admin 全站清空走管理接口
    bob_client.delete("/api/sessions")
    check("bob 清空只清自己", client.get("/api/admin/sessions").json()["sessions"] != [])

    # 7) 禁用即时踢出 + 保护规则
    bid = per["bob"]["id"]
    check("不能禁用自己", client.patch(f"/api/admin/users/{admin['id']}", json={"disabled": True}).status_code == 400)
    client.patch(f"/api/admin/users/{bid}", json={"disabled": True})
    check("禁用后 bob 请求 401", bob_client.get("/api/sessions").status_code == 401)
    client.patch(f"/api/admin/users/{bid}", json={"disabled": False, "password": "newpass123"})
    check("重置密码后可登录", bob_client.post("/api/auth", json={"username": "bob", "password": "newpass123"}).status_code == 200)

    check("不能删自己", client.delete(f"/api/admin/users/{admin['id']}").status_code == 400)
    r = client.delete(f"/api/admin/users/{bid}")
    check("删除用户成功", r.status_code == 200)
    check("被删用户登录 401", bob_client.post("/api/auth", json={"username": "bob", "password": "newpass123"}).status_code == 401)

    # 8) 自助注册（ALLOW_REGISTRATION=1）：注册即登录、只能拿到 user 角色、大小写查重
    reg_client = TestClient(appmain.app)
    r = reg_client.post("/api/auth/register", json={"username": "carol", "password": "carol123456"})
    check("注册成功且角色为 user", r.status_code == 200 and r.json()["user"]["role"] == "user")
    check("注册即登录（cookie 生效）", reg_client.get("/api/sessions").status_code == 200)
    r = reg_client.post(
        "/api/auth/register",
        json={"username": "carol", "password": "carol123456", "role": "admin"},  # 试图提权
    )
    check("重名注册 400", r.status_code == 400)
    check(
        "大小写变体也算重名",
        reg_client.post("/api/auth/register", json={"username": "Carol", "password": "carol123456"}).status_code == 400,
    )
    check("注册账号无管理权限", reg_client.get("/api/admin/users").status_code == 403)
    check(
        "注册账号短密码被拒",
        TestClient(appmain.app).post("/api/auth/register", json={"username": "dave", "password": "123"}).status_code == 400,
    )

    # 9) 登出
    client.post("/api/auth/logout")
    check("登出后 401", client.get("/api/sessions").status_code == 401)

# 10) open 模式（模拟本地开发：用户表为空且无 ACCESS_CODE）→ 闸门放行、无身份
userdb.DB_PATH = str(TMP / "users_open.db")  # 空用户库
r = client.post("/api/sessions", json={"kind": "chat", "query": "open", "result": FAKE_RESULT})
check("open 模式放行", r.status_code == 200)
check("open 模式归属 None（旧行为）", r.json()["user_id"] is None)
ids = [s["id"] for s in client.get("/api/sessions").json()["sessions"]]
check("open 模式列表不过滤（旧行为）", r.json()["id"] in ids and legacy["id"] in ids)

print(f"\n全部 {PASS} 项通过，临时库：{TMP}")
