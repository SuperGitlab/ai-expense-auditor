"""
向量存储模块
直接封装chromadb客户端（不引入langchain-chroma，减少依赖）

注意：
- 持久化路径绝对化，避免不同CWD启动产生两套库
- get_or_create_collection不传默认embedding_function（避免chromadb下载onnx模型），
  向量由调用方（embeddings模块）显式计算后传入
"""
import logging  # 标准日志：出错时logger.error记录，调用方拿到None/空结果自行降级
from pathlib import Path  # 面向对象的路径操作（.resolve()把相对路径转绝对路径）
from typing import Any, Optional  # 类型标注：Any=任意类型，Optional[X]=X或None

import chromadb  # 向量数据库本体（嵌入式，无需独立服务，数据落本地目录）
from chromadb.config import Settings as ChromaSettings  # chromadb的配置类（改名避免和本项目Settings混淆）

from app.config import settings  # 本项目配置（当前未直接用，保留）
from app.rag.embeddings import get_embeddings  # embedding工厂：文本→1024维向量（调GLM接口）

# 以本模块名建logger，日志能定位到来源文件
logger = logging.getLogger(__name__)

# 持久化目录绝对化：
# 本文件在 backend/app/rag/vectorstore.py，向上三级回到 backend/，
# 拼上 data/chroma → 无论从哪个工作目录启动，库都固定落在 backend/data/chroma，
# 避免"相对路径随CWD漂移，产生两套库"的经典坑（.env里的CHROMA_PERSIST_DIR实际未用）
CHROMA_DIR = (Path(__file__).resolve().parent.parent.parent / "data" / "chroma").resolve()

# chromadb客户端的单例缓存：None表示还没创建过
_client: Optional[chromadb.ClientAPI] = None


def get_client() -> Optional[chromadb.ClientAPI]:
    """获取chromadb持久化客户端（单例；失败返回None由调用方降级）"""
    # global声明：本函数要修改模块级的_client变量（Python里函数内赋值默认是局部变量）
    global _client
    if _client is None:  # 第一次调用才真正初始化（懒加载，和数据库engine一个思路）
        try:
            CHROMA_DIR.mkdir(parents=True, exist_ok=True)  # 目录不存在就建（parents=True连父目录一起建）
            _client = chromadb.PersistentClient(  # "持久化"客户端：数据自动落盘到path，重启不丢
                path=str(CHROMA_DIR),  # 落盘位置
                settings=ChromaSettings(anonymized_telemetry=False),  # 关闭匿名遥测（不往chroma官方发数据）
            )
        except Exception as e:  # 初始化失败不抛异常炸掉整个应用
            logger.error(f"ChromaDB初始化失败: {e}")
            return None  # 返回None，调用方据此降级（比如知识库不可用就跳过RAG检索）
    return _client  # 第二次起直接返回缓存的那一个客户端（全项目共用）


def get_collection(name: str, create: bool = True) -> Optional[Any]:
    """
    获取集合（cosine相似度；不传embedding_function，向量显式计算）
    （"集合"≈关系库里的"表"；不存在的名字就顺手创建）
    """
    client = get_client()  # 先拿客户端
    if client is None:  # 客户端都起不来（ChromaDB不可用）
        return None
    try:
        # get_or_create：有这个集合就用，没有就建——天然幂等，重复调用无副作用
        return client.get_or_create_collection(
            name=name,
            # 相似度算法用余弦距离（衡量向量夹角，与向量长度无关，适合文本语义比较）
            # chromadb默认是欧氏距离（L2），这里显式改成cosine
            metadata={"hnsw:space": "cosine"},
            # 故意不传embedding_function：chromadb默认会下载一个本地onnx模型来算向量，
            # 本项目统一用GLM的embedding-3（在embeddings模块），所以向量全由调用方算好再传入
        )
    except Exception as e:
        logger.error(f"获取集合 {name} 失败: {e}")
        return None


class VectorStore:
    """
    向量存储封装：文档入库与相似度查询
    （一个实例对应一个集合；KnowledgeBaseManager开了两个：制度库+案例库）
    """

    def __init__(self, collection_name: str):
        self.collection_name = collection_name  # 记住自己管哪个集合（表名）
        self.embeddings = get_embeddings()  # 拿到embedding对象（内部封装GLM接口调用）

    def add_documents(self, texts: list[str], metadatas: list[dict], ids: list[str]) -> int:
        """
        文档批量入库（文本→向量→chromadb）
        Returns: 成功入库条数（失败返回0）
        """
        collection = get_collection(self.collection_name)  # 打开集合
        if collection is None or not texts:  # 库不可用 / 没有文本要入 → 0条
            return 0
        try:
            # 先把所有文本批量算成向量（一次API调用传一批，比逐条调省网络开销）
            vectors = self.embeddings.embed_documents(texts)
            collection.add(  # 真正写入：三个列表按下标一一对应
                embeddings=vectors,  # 向量（检索时比对这个）
                documents=texts,  # 原文（命中后返回给人看的就是它）
                metadatas=metadatas,  # 标签（来源/章节，可按条件过滤）
                ids=ids,  # 主键（重复ID会报错，所以入库方生成了uuid）
            )
            return len(texts)  # 返回入库条数
        except Exception as e:  # 任何一步失败（网络/接口/写盘）都不炸应用
            logger.error(f"[{self.collection_name}] 文档入库失败: {e}")
            return 0

    def query(self, text: str, k: int = 3) -> list[dict]:
        """
        相似度查询
        Returns: [{document, metadata, distance}]；不可用/为空时返回[]
        """
        collection = get_collection(self.collection_name)  # 打开集合
        if collection is None:  # 库不可用
            return []
        try:
            if collection.count() == 0:  # 空库查询没意义（也省一次embedding调用费）
                return []
            vector = self.embeddings.embed_query(text)  # 把查询句也变成向量（和入库用同一个模型，向量空间才一致）
            result = collection.query(  # 向量近邻搜索（内部走HNSW索引，不是逐条遍历）
                query_embeddings=[vector],  # 注意是列表：chromadb支持一次查多句，这里只查一句
                n_results=min(k, collection.count()),  # 要几条结果（库里不足k条就要count条，防报错）
                include=["documents", "metadatas", "distances"],  # 结果里带原文/标签/距离
            )
            docs = result.get("documents") or [[]]  # chromadb返回的结构是"列表的列表"，取不到给个空壳防崩
            metas = result.get("metadatas") or [[]]
            dists = result.get("distances") or [[]]
            # 三个平行列表zip成一个个字典，调用方好处理：{document, metadata, distance}
            # distance是余弦距离：越小越相似（0=方向一致）
            return [
                {
                    "document": doc,
                    "metadata": meta or {},
                    "distance": dist,
                }
                for doc, meta, dist in zip(docs[0], metas[0], dists[0])
            ]
        except Exception as e:
            logger.error(f"[{self.collection_name}] 查询失败: {e}")
            return []

    def count(self) -> int:
        """集合内文档数（不可用返回-1）"""
        collection = get_collection(self.collection_name)
        if collection is None:
            return -1  # 约定-1表示"库不可用"，区别于0（库可用但为空）
        try:
            return collection.count()
        except Exception:
            return -1

    def reset(self) -> bool:
        """清空集合（开发调试用）"""
        client = get_client()  # 注意：删集合要拿client（集合级操作挂在client上）
        if client is None:
            return False
        try:
            # 删的是整个集合（≈DROP TABLE），不是逐条删——比一条条删快得多
            client.delete_collection(self.collection_name)
            return True
        except Exception:
            return False


def is_available() -> bool:
    """ChromaDB是否可用"""
    return get_client() is not None  # 能拿到客户端就是可用（None=初始化失败）
