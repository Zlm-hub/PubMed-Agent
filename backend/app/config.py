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
NCBI_API_KEY = os.getenv("NCBI_API_KEY") or _alias("PubMed-APIkey")
NCBI_EMAIL = os.getenv("NCBI_EMAIL", "demo@example.com")
NCBI_TOOL = os.getenv("NCBI_TOOL", "pubmed-analytics")

# 阿里云百炼（OpenAI 兼容网关）
DASHSCOPE_API_KEY = os.getenv("DASHSCOPE_API_KEY") or _alias("QW-APIkey")
DASHSCOPE_BASE_URL = (
    os.getenv("DASHSCOPE_BASE_URL")
    or _openai_compatible_url()
    or "https://dashscope.aliyuncs.com/compatible-mode/v1"
)
LLM_MODEL = os.getenv("LLM_MODEL", "qwen-plus")

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
PRESETS = [s.strip() for s in os.getenv("PRESETS", "Alzheimer,CRISPR cancer,COVID-19 vaccine,渐冻症").split(",") if s.strip()]

# 监控日志（docs/监控日志设计方案.md）：按天轮转双文件，app 留 14 天 / error 留 30 天
LOG_LEVEL = os.getenv("LOG_LEVEL", "INFO")
LOG_DIR = os.getenv("LOG_DIR") or os.path.normpath(
    os.path.join(os.path.dirname(__file__), "..", "logs")
)
LOG_RETENTION_DAYS_APP = int(os.getenv("LOG_RETENTION_DAYS_APP", "14"))
LOG_RETENTION_DAYS_ERROR = int(os.getenv("LOG_RETENTION_DAYS_ERROR", "30"))

# 文件缓存目录（演示预缓存落盘处）
CACHE_DIR = os.getenv("CACHE_DIR", os.path.join(os.path.dirname(__file__), "..", "cache"))
