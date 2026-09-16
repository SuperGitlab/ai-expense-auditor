"""
v3 迁移 CLI：python scripts/migrate_v3.py [--url DATABASE_URL]
默认用 app 配置的 DATABASE_URL
"""
import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from sqlalchemy import create_engine  # noqa: E402

from app.config import settings  # noqa: E402
from app.db_migrations import migrate_v3  # noqa: E402


def main() -> None:
    parser = argparse.ArgumentParser(description="agent_node_runs 节点轨迹表 v3 幂等迁移")
    parser.add_argument("--url", default=None, help="数据库连接串（默认取 .env 的 DATABASE_URL）")
    args = parser.parse_args()
    url = args.url or settings.DATABASE_URL
    engine = create_engine(url)
    try:
        migrate_v3(engine)
        print("migrate_v3 完成")
    finally:
        engine.dispose()


if __name__ == "__main__":
    main()
