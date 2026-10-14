"""后端配置：从环境变量读取，支持 .env。

变量名兼容两套写法（标准名优先，取不到再回落到 .env 里的简写名）：
  NCBI_API_KEY       ← PubMed-APIkey
  DASHSCOPE_API_KEY  ← QW-APIkey
  DASHSCOPE_BASE_URL ← QW-URL 里标着 openAiCompatible 的那条

QW-URL 在 .env 里出现两次（openAiCompatible 与 dashScope 两条路径），dotenv 只会保留
最后一条，所以这里直接读原始文件、按标签挑出 OpenAI 兼容那条，而不是靠 os.getenv。
"""
import os
import re

from dotenv import find_dotenv, load_dotenv

DOTENV_PATH = find_dotenv()
load_dotenv(DOTENV_PATH)


def _read_dotenv() -> str:
    if not DOTENV_PATH:
        return ""
    try:
        with open(DOTENV_PATH, encoding="utf-8") as f:
            return f.read()
    except OSError:
        return ""


_RAW = _read_dotenv()


def _alias(name: str) -> str:
    """从 .env 原文里取一个变量（用于标准名缺失时的回落）。"""
    m = re.search(rf"(?im)^\s*{re.escape(name)}\s*=\s*(\S+)", _RAW)
    return m.group(1).strip() if m else ""


def _openai_compatible_url() -> str:
    """挑出 .env 里标注为 OpenAI 兼容的那条网关地址。"""
    for line in _RAW.splitlines():
        if "http" in line and "openai" in line.lower():
            m = re.search(r"https?://\S+", line)
            if m:
                return m.group(0).rstrip("/")
    return ""


# NCBI E-utilities
# 标准名 → 简写名（环境变量）→ 简写名（.env 原文）。加了环境变量这一档，
# 是为了让纯容器部署（不挂载 .env 文件、只注入环境变量）也能取到密钥。
NCBI_API_KEY = (
    os.getenv("NCBI_API_KEY") or os.getenv("PubMed-APIkey") or _alias("PubMed-APIkey")
)
NCBI_EMAIL = os.getenv("NCBI_EMAIL", "demo@example.com")
NCBI_TOOL = os.getenv("NCBI_TOOL", "pubmed-analytics")

# 阿里云百炼（OpenAI 兼容网关）
DASHSCOPE_API_KEY = (
    os.getenv("DASHSCOPE_API_KEY") or os.getenv("QW-APIkey") or _alias("QW-APIkey")
)
DASHSCOPE_BASE_URL = (
    os.getenv("DASHSCOPE_BASE_URL")
    or _openai_compatible_url()
    or "https://dashscope.aliyuncs.com/compatible-mode/v1"
)
LLM_MODEL = os.getenv("LLM_MODEL", "qwen-plus")

# 词云 / MeSH 主题词中文化（英文原词 → 中文阅读辅助）：默认开，置 0 即回英文。
# 词典命中零开销；未命中一次性批量机翻并落 literature.db::word_zh（见 app/wordzh.py）。
WORD_ZH = os.getenv("WORD_ZH", "1") == "1"
WORD_ZH_MODEL = os.getenv("WORD_ZH_MODEL") or LLM_MODEL

# 检索上限（锁定决策 5：前 1000 篇）
MAX_RESULTS = int(os.getenv("MAX_RESULTS", "1000"))

# 无 key 时走示例综述（仅演示 UI）
MOCK_LLM = os.getenv("MOCK_LLM", "0") == "1"

# 中文查询改写（L0 映射表 → L1 LLM）：仅对含中文的输入生效，关掉则行为与旧版一致
QUERY_REWRITE = os.getenv("QUERY_REWRITE", "1") == "1"

# 综述取摘要篇数
REVIEW_TOP_N = int(os.getenv("REVIEW_TOP_N", "30"))

# 缓存 TTL（秒）
CACHE_TTL = int(os.getenv("CACHE_TTL", "3600"))

# 演示预置关键词（一键演示，现场不翻车；渐冻症走中文改写链路）
PRESETS = [s.strip() for s in os.getenv("PRESETS", "阿尔茨海默病,肺癌,高血压,渐冻症").split(",") if s.strip()]

# 监控日志（docs/监控日志设计方案.md）：按天轮转双文件，app 留 14 天 / error 留 30 天
LOG_LEVEL = os.getenv("LOG_LEVEL", "INFO")
LOG_DIR = os.getenv("LOG_DIR") or os.path.normpath(
    os.path.join(os.path.dirname(__file__), "..", "logs")
)
LOG_RETENTION_DAYS_APP = int(os.getenv("LOG_RETENTION_DAYS_APP", "14"))
LOG_RETENTION_DAYS_ERROR = int(os.getenv("LOG_RETENTION_DAYS_ERROR", "30"))

# 文件缓存目录（演示预缓存落盘处）
CACHE_DIR = os.getenv("CACHE_DIR", os.path.join(os.path.dirname(__file__), "..", "cache"))

# ---- 部署（公网 / 单端口）-----------------------------------------------------
# 访问口令：设置后所有 /api/*（除健康检查与鉴权）都必须携带口令，防止公开链接被
# 转发后他人白嫖 DashScope / NCBI 密钥。本地开发留空 = 不校验，行为与旧版一致。
ACCESS_CODE = os.getenv("ACCESS_CODE", "")

# 访问口令的 cookie 名。口令用 cookie 传递（而非仅自定义头），是因为流式分析走
# EventSource，而 EventSource 无法设置自定义请求头；同源请求会自动带上 cookie，
# 于是无需改动已验证的流式链路。
ACCESS_COOKIE = os.getenv("ACCESS_COOKIE", "pa_auth")

# 口令 cookie 是否仅在 HTTPS 下发送。生产环境用 https（如 nginx 终止 TLS）时建议置 1。
ACCESS_COOKIE_SECURE = os.getenv("ACCESS_COOKIE_SECURE", "0") == "1"

# CORS 允许来源（逗号分隔）。单端口同源部署无需设置；本地跨端口开发用内置默认值。
ALLOWED_ORIGINS = [s.strip() for s in os.getenv("ALLOWED_ORIGINS", "").split(",") if s.strip()]

# 前端构建产物目录：存在则 FastAPI 直接托管（单端口部署，无需额外 web 服务器）。
FRONTEND_DIST = os.getenv("FRONTEND_DIST") or os.path.normpath(
    os.path.join(os.path.dirname(__file__), "..", "..", "frontend", "dist")
)

# ---- 用户与管理员（2026-09-20 拍板：管理员建号制，见 app/userdb.py）----------------
# 首启建号：users 表为空且两者均非空时，自动创建 role='admin' 的管理员。
ADMIN_USERNAME = os.getenv("ADMIN_USERNAME", "")
ADMIN_PASSWORD = os.getenv("ADMIN_PASSWORD", "")

# 登录态 token 的 HMAC 签名密钥。未配置时 userdb 首次生成 64 位 hex 落盘
# data/auth_secret.key（重启不掉线）。多实例部署务必显式配置同一个值。
AUTH_SECRET = os.getenv("AUTH_SECRET", "")

# 登录态 cookie 名（与旧共享口令 cookie ACCESS_COOKIE 并存：登录时清掉旧 cookie）
AUTH_COOKIE = os.getenv("AUTH_COOKIE", "pa_session")

# 自助注册开关（2026-09-20 用户要求补上）：
#   0（默认）= 关闭，账号只能由管理员在「管理后台」创建（拍板方案 A 的默认形态）；
#   1       = 登录页显示「注册」入口。
# 无论开关如何，**自助注册的账号一律 role='user'**——管理员角色只能由现有管理员
# 在后台授予，防止越权提权。
ALLOW_REGISTRATION = os.getenv("ALLOW_REGISTRATION", "0") == "1"

# ---- 免费试用额度（2026-09-21 用户要求：服务器版「每个账号免费试用 3 次」）----------
# 0（默认）= 不限制、不计数——本地开发保持无感，行为与旧版完全一致。
# >0       = 每个**普通账号**最多做 N 次分析（POST /api/analyze 与 /api/analyze/stream
#            各算一次，含缓存命中；报告生成只是复用快照，不计次）。
# 豁免：管理员账号（role=admin）与运维通道（X-Access-Code）不计数、不受限；
#       open 模式（无身份）本就不启用额度。
FREE_TRIAL_LIMIT = int(os.getenv("FREE_TRIAL_LIMIT", "0") or "0")

# 联系方式：额度用尽时拼进提示语（如 `QQ3184331768`）。留空则只说「请联系管理员」。
ADMIN_CONTACT = os.getenv("ADMIN_CONTACT", "")
