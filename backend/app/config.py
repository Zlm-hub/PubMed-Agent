"""后端配置：从环境变量读取，支持 .env。"""
import os

from dotenv import load_dotenv

load_dotenv()

# NCBI E-utilities
NCBI_API_KEY = os.getenv("NCBI_API_KEY", "")
NCBI_EMAIL = os.getenv("NCBI_EMAIL", "demo@example.com")
NCBI_TOOL = os.getenv("NCBI_TOOL", "pubmed-analytics")

# 阿里云百炼 DashScope（OpenAI 兼容）
DASHSCOPE_API_KEY = os.getenv("DASHSCOPE_API_KEY", "")
DASHSCOPE_BASE_URL = os.getenv(
    "DASHSCOPE_BASE_URL", "https://dashscope.aliyuncs.com/compatible-mode/v1"
)
LLM_MODEL = os.getenv("LLM_MODEL", "qwen-plus")

# 检索上限（锁定决策 5：前 1000 篇）
MAX_RESULTS = int(os.getenv("MAX_RESULTS", "1000"))

# 无 key 时走示例综述（仅演示 UI）
MOCK_LLM = os.getenv("MOCK_LLM", "0") == "1"

# 综述取摘要篇数
REVIEW_TOP_N = int(os.getenv("REVIEW_TOP_N", "30"))

# 缓存 TTL（秒）
CACHE_TTL = int(os.getenv("CACHE_TTL", "3600"))

# 演示预置关键词（一键演示，现场不翻车）
PRESETS = [s.strip() for s in os.getenv("PRESETS", "Alzheimer,CRISPR cancer,COVID-19 vaccine").split(",") if s.strip()]

# 文件缓存目录（演示预缓存落盘处）
CACHE_DIR = os.getenv("CACHE_DIR", os.path.join(os.path.dirname(__file__), "..", "cache"))
