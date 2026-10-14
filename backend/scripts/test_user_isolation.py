"""用户体系隔离场景回归测试（2026-09-20 用户/管理员功能配套）。

不碰真实数据：users.db / sessions.db 全部指向临时目录。
运行：backend/.venv/Scripts/python.exe scripts/test_user_isolation.py
覆盖：首启建号 → 存量划归 → 双用户隔离（读写双向）→ 报告复用键按用户分开
      → admin 全局视图 → 禁用即时失效 → 保护规则。
"""
import os
import sys
import tempfile
from pathlib import Path

# 必须在导入 config 前设置环境变量
TMP = Path(tempfile.mkdtemp(prefix="pa_auth_test_"))
os.environ["ADMIN_USERNAME"] = "admin"
os.environ["ADMIN_PASSWORD"] = "admin123"
os.environ["ACCESS_CODE"] = ""

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app import sessiondb, userdb  # noqa: E402

userdb.DB_PATH = str(TMP / "users.db")
sessiondb.DB_PATH = str(TMP / "sessions.db")

PASS = 0


def check(name: str, cond: bool) -> None:
    global PASS
    tag = "PASS" if cond else "FAIL"
    print(f"[{tag}] {name}")
    if not cond:
        sys.exit(1)
    PASS += 1


FAKE_RESULT = {"query": "x", "total": 0, "returned": 0, "stats": {"if_statistics": {"known_count": 0}}}

# 1) 模拟存量：无归属会话（迁移前的老数据）
old = sessiondb.create_thread("old query", FAKE_RESULT, title="存量会话")
check("存量会话 user_id 为 NULL", old["user_id"] is None)

# 2) 首启建管理员
admin = userdb.bootstrap()
check("bootstrap 创建 admin", admin is not None and admin["role"] == "admin")
check("重复 bootstrap 幂等", userdb.bootstrap() is None)

# 3) 存量划归 admin
moved = sessiondb.claim_orphans(admin["id"])
check(f"存量会话划归 admin（{moved} 条）", moved == 1)
check("划归后 admin 可见", sessiondb.list_threads(user_id=admin["id"])[0]["id"] == old["id"])

# 4) 登录 token
tok = userdb.make_token(admin["id"])
check("token 校验通过", userdb.verify_token(tok)["id"] == admin["id"])
check("篡改 token 拒绝", userdb.verify_token(tok[:-4] + "beef") is None)
check("authenticate 正确密码", userdb.authenticate("admin", "admin123") is not None)
check("authenticate 错误密码", userdb.authenticate("admin", "wrong!") is None)

# 5) 建普通用户 bob + 双向隔离
bob = userdb.create_user("bob", "bob123456", role="user", display_name="测试用户")
check("管理员建号 bob", bob["role"] == "user")

bob_thread = sessiondb.create_thread("lung cancer", FAKE_RESULT, title="bob 的会话", user_id=bob["id"])
admin_thread = sessiondb.create_thread("alzheimer", FAKE_RESULT, title="admin 的会话", user_id=admin["id"])

check("bob 只见自己的会话", [s["id"] for s in sessiondb.list_threads(user_id=bob["id"])] == [bob_thread["id"]])
admin_ids = {s["id"] for s in sessiondb.list_threads(user_id=admin["id"])}
check("admin 侧栏只见自己的", admin_ids == {admin_thread["id"], old["id"]})
check("bob 打不开 admin 的线程", sessiondb.get_thread(admin_thread["id"], user_id=bob["id"]) is None)
check("bob 不能往 admin 线程追加", sessiondb.append_exchange(admin_thread["id"], "q", FAKE_RESULT, user_id=bob["id"]) is None)
check("bob 删不掉 admin 的线程", sessiondb.delete(admin_thread["id"], user_id=bob["id"]) is False)
check("admin 能看 bob 的线程（管理权限）", sessiondb.get_thread(bob_thread["id"], user_id=None) is not None)

# 6) 追问只落在自己线程
appended = sessiondb.append_exchange(bob_thread["id"], "follow up", FAKE_RESULT, user_id=bob["id"])
check("bob 追问自己的线程", appended is not None and appended["exchanges"] == 2)

# 7) 报告复用键按用户分开：同词不同人不互踩
r1 = sessiondb.save_report("lung cancer", FAKE_RESULT, user_id=bob["id"])
r2 = sessiondb.save_report("lung cancer", FAKE_RESULT, user_id=admin["id"])
check("同词报告按用户分开", r1["id"] != r2["id"])
r1b = sessiondb.save_report("lung cancer", FAKE_RESULT, user_id=bob["id"])
check("同人同词复用同一条", r1b["id"] == r1["id"])

# 8) 统计与清空范围
stats = sessiondb.counts_by_user()
check("统计含 admin 与 bob", stats.get(admin["id"], {}).get("chats", 0) >= 2 and stats.get(bob["id"], {}).get("chats", 0) >= 1)
sessiondb.clear(user_id=bob["id"])
admin_after = {s["id"] for s in sessiondb.list_threads(user_id=admin["id"])}
check(
    "清空只清自己",
    sessiondb.list_threads(user_id=bob["id"]) == [] and bob_thread["id"] not in admin_after and r2["id"] in admin_after,
)

# 9) 禁用即时失效 + 保护规则
bob_tok = userdb.make_token(bob["id"])
check("禁用前 token 有效", userdb.verify_token(bob_tok) is not None)
userdb.update_user(bob["id"], disabled=True)
check("禁用后 token 即时失效", userdb.verify_token(bob_tok) is None)
userdb.update_user(bob["id"], disabled=False)

# 10) 建号参数校验
for bad in [("a", "123456"), ("bob", "123456"), ("新用户", "12345")]:
    try:
        userdb.create_user(*bad)
        check(f"非法参数被拒 {bad}", False)
    except ValueError:
        check(f"非法参数被拒 {bad}", True)

print(f"\n全部 {PASS} 项通过，临时库：{TMP}")
