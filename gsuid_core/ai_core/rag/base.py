"""RAG模块基础功能 - 共享常量和工具函数"""

import os
import json
import uuid
import hashlib
import threading
from typing import Final, Union

from fastembed import TextEmbedding, SparseTextEmbedding
from qdrant_client import AsyncQdrantClient
from huggingface_hub import constants as hf_constants, snapshot_download

from gsuid_core.logger import logger
from gsuid_core.data_store import AI_CORE_PATH
from gsuid_core.ai_core.configs.ai_config import ai_config, rerank_model_config, local_embedding_config

# ============== 向量库配置 ==============
DIMENSION: Final[int] = 512

# Embedding模型相关
EMBEDDING_MODEL_NAME: Final[str] = local_embedding_config.get_config("embedding_model_name").data
MODELS_CACHE = AI_CORE_PATH / "models_cache"
DB_PATH = AI_CORE_PATH / "local_qdrant_db"

# Reranker模型相关
RERANK_MODELS_CACHE = AI_CORE_PATH / "rerank_models_cache"
RERANKER_MODEL_NAME: Final[str] = rerank_model_config.get_config("rerank_model_name").data

# ============== Collection名称 ==============
TOOLS_COLLECTION_NAME: Final[str] = "bot_tools"
KNOWLEDGE_COLLECTION_NAME: Final[str] = "knowledge"
IMAGE_COLLECTION_NAME: Final[str] = "image"


# ============== 模型HF仓库映射 ==============
def _get_embedding_hf_repo(model_name: str) -> str:
    """根据embedding模型名称获取对应的HuggingFace仓库名

    特别处理：只要文件名中包含 bge-small-zh-v1.5，就使用 Qdrant/bge-small-zh-v1.5
    """
    if "bge-small-zh-v1.5" in model_name:
        return "Qdrant/bge-small-zh-v1.5"
    return model_name


EMBEDDING_HF_REPO: Final[str] = _get_embedding_hf_repo(EMBEDDING_MODEL_NAME)
SPARSE_HF_REPO: Final[str] = "Qdrant/bm25"
RERANKER_HF_REPO: Final[str] = RERANKER_MODEL_NAME  # BAAI/bge-reranker-base


# ============== 配置开关（动态读取，避免模块加载时配置文件不存在导致默认值错误） ==============
def is_enable_ai() -> bool:
    return ai_config.get_config("enable").data


def is_enable_rerank() -> bool:
    return ai_config.get_config("enable_rerank").data


def _get_hf_endpoint() -> str:
    """获取HuggingFace服务器地址"""
    return ai_config.get_config("hf_endpoint").data


def pre_download_models():
    """使用huggingface_hub提前下载所有模型到缓存目录

    下载三个模型：
    1. Embedding模型: Qdrant/bge-small-zh-v1.5 -> MODELS_CACHE
    2. Sparse模型: Qdrant/bm25 -> MODELS_CACHE
    3. Reranker模型: BAAI/bge-reranker-base -> RERANK_MODELS_CACHE
    """
    if not is_enable_ai():
        return

    hf_endpoint = _get_hf_endpoint()
    # 设置HF_ENDPOINT环境变量，并同步更新huggingface_hub.constants.ENDPOINT
    # 因为huggingface_hub在模块导入时就缓存了ENDPOINT值，仅修改os.environ不会生效
    old_endpoint = os.environ.get("HF_ENDPOINT")
    old_hf_constant = getattr(hf_constants, "ENDPOINT", None)
    os.environ["HF_ENDPOINT"] = hf_endpoint
    hf_constants.ENDPOINT = hf_endpoint.rstrip("/")
    logger.info(f"🧠 [RAG] HuggingFace 端点已设置: HF_ENDPOINT={hf_constants.ENDPOINT}")

    try:
        # 下载Embedding模型
        logger.info(f"🧠 [RAG] 预下载Embedding模型: {EMBEDDING_HF_REPO}")
        snapshot_download(
            repo_id=EMBEDDING_HF_REPO,
            cache_dir=str(MODELS_CACHE),
        )
        logger.info("🧠 [RAG] Embedding模型预下载完成")

        # 下载Sparse模型
        logger.info(f"🧠 [RAG] 预下载Sparse模型: {SPARSE_HF_REPO}")
        snapshot_download(
            repo_id=SPARSE_HF_REPO,
            cache_dir=str(MODELS_CACHE),
        )
        logger.info("🧠 [RAG] Sparse模型预下载完成")

        # 下载Reranker模型（如果启用了rerank）
        if is_enable_rerank():
            logger.info(f"🧠 [RAG] 预下载Reranker模型: {RERANKER_HF_REPO}")
            snapshot_download(
                repo_id=RERANKER_HF_REPO,
                cache_dir=str(RERANK_MODELS_CACHE),
            )
            logger.info("🧠 [RAG] Reranker模型预下载完成")
    except Exception as e:
        logger.warning(f"🧠 [RAG] 模型预下载失败，将在使用时尝试加载: {e}")
    finally:
        # 恢复原来的HF_ENDPOINT和huggingface_hub常量
        if old_endpoint is not None:
            os.environ["HF_ENDPOINT"] = old_endpoint
        elif "HF_ENDPOINT" in os.environ:
            del os.environ["HF_ENDPOINT"]
        if old_hf_constant is not None:
            hf_constants.ENDPOINT = old_hf_constant


embedding_model: "Union[TextEmbedding, None]" = None
client: "Union[AsyncQdrantClient, None]" = None
# 全局 Sparse Embedding 模型（懒加载，线程安全）
_sparse_model = None
_sparse_model_lock = threading.Lock()


def _get_sparse_model():
    """隐患三修复：添加线程锁防止并发初始化模型"""
    global _sparse_model

    if not is_enable_ai():
        return

    if _sparse_model is None:
        with _sparse_model_lock:
            # 双重检查锁定
            if _sparse_model is None:
                try:
                    _sparse_model = SparseTextEmbedding(
                        model_name="Qdrant/bm25",
                        cache_dir=str(MODELS_CACHE),
                        threads=2,
                        local_files_only=True,
                    )
                except Exception as e:
                    logger.warning(f"🧠 [Memory] SparseTextEmbedding 初始化失败: {e}")
    return _sparse_model


def init_embedding_model():
    """初始化Embedding模型和Qdrant客户端"""
    global embedding_model, client

    if not is_enable_ai():
        return

    # 防止重复初始化，导致Qdrant文件锁冲突
    if client is not None:
        return

    embedding_model = TextEmbedding(
        model_name=EMBEDDING_MODEL_NAME,
        cache_dir=str(MODELS_CACHE),
        threads=2,
        local_files_only=True,
    )
    client = AsyncQdrantClient(path=str(DB_PATH))


def get_point_id(id_str: str) -> str:
    """生成向量化存储的唯一ID

    使用UUID5和DNS命名空间生成确定性的UUID，
    相同id_str始终生成相同的UUID，确保幂等性。

    Args:
        id_str: 唯一标识符字符串

    Returns:
        唯一的UUID字符串
    """
    return str(uuid.uuid5(uuid.NAMESPACE_DNS, id_str))


def calculate_hash(content: dict) -> str:
    """计算内容字典的MD5哈希

    用于检测内容是否有变更，支持知识库增量更新判断。
    排序键以确保相同内容产生相同的哈希值。

    Args:
        content: 要计算哈希的内容字典

    Returns:
        MD5哈希值（32位十六进制字符串）
    """
    json_str = json.dumps(content, sort_keys=True, ensure_ascii=False)
    return hashlib.md5(json_str.encode("utf-8")).hexdigest()
