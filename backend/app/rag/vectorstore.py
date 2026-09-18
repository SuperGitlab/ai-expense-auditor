"""
向量存储模块
直接封装pymilvus的MilvusClient（不引入langchain-milvus，减少依赖）

注意：
- Milvus是独立服务（standalone部署，地址由MILVUS_URI配置），不再依赖本地目录——
  顺带消除了旧版backend/worker两进程共享嵌入式sqlite目录的并发写隐患
- 集合schema：id主键 + text原文 + vector向量（dim与GLM embedding一致），
  其余metadata走动态字段（enable_dynamic_field），无需逐个声明
- 分数语义换算：Milvus COSINE分数越大越相似，本模块统一换算成
  distance = 1 - score（越小越相似），保持对上层（retriever/agent）的既有契约
"""
import logging  # 标准日志：出错时logger.error记录，调用方拿到None/空结果自行降级
from typing import Optional  # 类型标注：Optional[X]=X或None

from pymilvus import DataType, MilvusClient  # Milvus官方SDK（MilvusClient=新版统一入口）

from app.config import settings  # 本项目配置（MILVUS_URI、EMBEDDING_DIMENSIONS）
from app.rag.embeddings import get_embeddings  # embedding工厂：文本→1024维向量（调GLM接口）

# 以本模块名建logger，日志能定位到来源文件
logger = logging.getLogger(__name__)

# Milvus客户端的单例缓存：None表示还没创建过
_client: Optional[MilvusClient] = None


def get_client() -> Optional[MilvusClient]:
    """获取Milvus客户端（单例；连接失败返回None由调用方降级）"""
    # global声明：本函数要修改模块级的_client变量（Python里函数内赋值默认是局部变量）
    global _client
    if _client is None:  # 第一次调用才真正连接（懒加载，和数据库engine一个思路）
        try:
            _client = MilvusClient(uri=settings.MILVUS_URI)  # 构造时即建连，失败抛异常
        except Exception as e:  # 连不上不炸应用（比如Milvus机器没开机）
            logger.error(f"Milvus连接失败（{settings.MILVUS_URI}）: {e}")
            return None  # 返回None，调用方据此降级（比如知识库不可用就跳过RAG检索）
    return _client  # 第二次起直接返回缓存的那一个客户端（全项目共用）


def get_collection(name: str, create: bool = True) -> Optional[str]:
    """
    确保集合存在并返回集合名（cosine相似度HNSW索引；向量显式计算）
    MilvusClient按名字直接操作集合（不像chromadb返回collection对象），
    返回名字只为保持"None=服务不可用"的既有判断约定
    """
    client = get_client()  # 先拿客户端
    if client is None:  # 客户端都连不上（Milvus不可用）
        return None
    try:
        if not client.has_collection(name):  # 不存在才建——天然幂等，重复调用无副作用
            if not create:  # 显式不许建（当前无调用方用到，保留参数兼容签名）
                return None
            # 显式schema：主键+原文+向量三字段，auto_id=False（沿用chromadb时代的自定义字符串ID）
            schema = MilvusClient.create_schema(auto_id=False, enable_dynamic_field=True)
            schema.add_field("id", DataType.VARCHAR, is_primary=True, max_length=128)
            schema.add_field("vector", DataType.FLOAT_VECTOR, dim=settings.EMBEDDING_DIMENSIONS)
            schema.add_field("text", DataType.VARCHAR, max_length=65535)
            # 向量索引：HNSW图索引 + COSINE度量（与旧Chroma的hnsw:space=cosine对齐）
            index_params = MilvusClient.prepare_index_params()
            index_params.add_index(
                field_name="vector",
                index_type="HNSW",
                metric_type="COSINE",  # 文本语义比较看夹角不看模长
                params={"M": 16, "efConstruction": 200},  # 常规参数：召回/建索引速度折中
            )
            # 建集合并自动加载（建了索引即可搜，无需再手动load）
            client.create_collection(collection_name=name, schema=schema, index_params=index_params)
        return name
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
        文档批量入库（文本→向量→Milvus）
        Returns: 成功入库条数（失败返回0）
        """
        client = get_client()  # 先拿客户端与集合
        if client is None or get_collection(self.collection_name) is None or not texts:
            return 0  # 库不可用 / 没有文本要入 → 0条
        try:
            # 先把所有文本批量算成向量（一次API调用传一批，比逐条调省网络开销）
            vectors = self.embeddings.embed_documents(texts)
            # 每行一个dict：三字段显式给值，metadata拍平进动态字段（不能叫id/text/vector）
            rows = [
                {"id": rid, "vector": vec, "text": text, **(meta or {})}
                for rid, vec, text, meta in zip(ids, vectors, texts, metadatas)
            ]
            client.insert(collection_name=self.collection_name, data=rows)
            return len(texts)  # 返回入库条数
        except Exception as e:  # 任何一步失败（网络/embedding接口/Milvus写）都不炸应用
            logger.error(f"[{self.collection_name}] 文档入库失败: {e}")
            return 0

    def query(self, text: str, k: int = 3) -> list[dict]:
        """
        相似度查询
        Returns: [{document, metadata, distance}]；不可用时返回[]
        （distance越小越相似——由Milvus COSINE分数换算而来，语义与旧Chroma版一致）
        """
        client = get_client()  # 先拿客户端与集合
        if client is None or get_collection(self.collection_name) is None:
            return []  # 库不可用
        try:
            vector = self.embeddings.embed_query(text)  # 查询句变向量（与入库同模型，向量空间才一致）
            results = client.search(  # 向量近邻搜索（内部走HNSW索引，不是逐条遍历）
                collection_name=self.collection_name,
                data=[vector],  # 列表：支持一次查多句，这里只查一句
                limit=k,  # 要几条结果（库里不足k条自动少给，不会报错）
                output_fields=["*"],  # text + 全部动态metadata字段都带回来
            )
            hits = results[0] if results else []  # 取第一句查询的结果（结构是"列表的列表"）
            return [
                {
                    "document": (hit.get("entity") or {}).get("text", ""),
                    # metadata=除text外的全部动态字段（source/section/expense_id等）
                    "metadata": {key: value for key, value in (hit.get("entity") or {}).items()
                                 if key != "text"},
                    # Milvus COSINE的distance字段其实是相似度分数（越大越相似），
                    # 换算成余弦距离：1 - score，保持"越小越相似"的对外契约
                    "distance": 1 - (hit.get("distance") or 0.0),
                }
                for hit in hits
            ]
        except Exception as e:
            logger.error(f"[{self.collection_name}] 查询失败: {e}")
            return []

    def count(self) -> int:
        """集合内文档数（不可用返回-1；Milvus统计为近似值，仅展示用）"""
        client = get_client()
        if client is None or get_collection(self.collection_name) is None:
            return -1  # 约定-1表示"库不可用"，区别于0（库可用但为空）
        try:
            stats = client.get_collection_stats(self.collection_name)
            return int(stats.get("row_count", 0))
        except Exception:
            return -1

    def reset(self) -> bool:
        """清空集合（开发调试用）"""
        client = get_client()  # 注意：删集合是client级操作
        if client is None:
            return False
        try:
            # 删的是整个集合（≈DROP TABLE），不是逐条删——比一条条删快得多；
            # 下次get_collection/add时会按schema自动重建
            client.drop_collection(self.collection_name)
            return True
        except Exception:
            return False


def is_available() -> bool:
    """Milvus是否可用（连接成功且能应答一次真实请求）"""
    client = get_client()
    if client is None:
        return False  # 连接都没建立（None=初始化失败）
    try:
        client.list_collections()  # 发一次真实请求探活（不是只看连接对象存在）
        return True
    except Exception as e:
        logger.error(f"Milvus探活失败: {e}")
        return False
