"""
向量库窥探脚本（纯只读，不写入不修改任何数据）：
1. 列出 Milvus 里所有集合
2. 打印制度库 policies 前5条原文切块
3. 演示语义检索：拿一句话算向量，搜最相似的3条制度
用法：cd backend && uv run python scripts/peek_milvus.py
"""
import logging
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from pymilvus import MilvusClient  # noqa: E402

from app.config import settings  # noqa: E402
from app.rag.embeddings import get_embeddings  # noqa: E402

logging.basicConfig(level=logging.WARNING)

client = MilvusClient(uri=settings.MILVUS_URI)

print(client)

print("=== 集合列表 ===")
print(client.list_collections())

print("\n=== policies 表结构（describe_collection，相当于MySQL的DESC） ===")
schema = client.describe_collection(collection_name="policies")
for f in schema["fields"]:
    print(f)

print("\n=== 实际一行数据的全部字段（含动态字段，output_fields=['*']） ===")
rows_full = client.query(
    collection_name="policies", filter='id != ""', limit=1, output_fields=["*"]
)
if rows_full:
    print(list(rows_full[0].keys()))

print("\n=== policies 前5条（id/source/section/原文前80字） ===")
rows = client.query(
    collection_name="policies",
    filter='id != ""',
    limit=5,
    output_fields=["text", "source", "section"],
)
for r in rows:
    print(f"[{r.get('source')} / {r.get('section')}] {r.get('text', '')[:80]}...")

print("\n=== 语义检索演示：query='住宿费600元超标了吗' top3 ===")
vec = get_embeddings().embed_query("住宿费600元超标了吗")
hits = client.search(
    collection_name="policies",
    data=[vec],
    limit=3,
    output_fields=["text", "source", "section"],
)[0]
for h in hits:
    ent = h.get("entity") or {}
    # Milvus COSINE度量下，返回的distance字段装的其实是相似度分数（越大越像）
    print(
        f"相似度{round(h.get('distance', 0.0), 3)} "
        f"[{ent.get('source')} / {ent.get('section')}] {ent.get('text', '')[:80]}..."
    )
