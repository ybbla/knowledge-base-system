"""清空 MinIO 中的所有对象和桶。"""
import sys
sys.path.insert(0, "knowledge_base_system")

from minio import Minio
from app.core.config import settings


def clear_minio():
    client = Minio(
        settings.minio_endpoint,
        access_key=settings.minio_access_key,
        secret_key=settings.minio_secret_key,
        secure=settings.minio_secure,
    )

    buckets = client.list_buckets()
    print(f"发现 {len(buckets)} 个桶")

    for bucket in buckets:
        name = bucket.name
        print(f"\n处理桶: {name}")

        # 列出并删除所有对象
        objects = list(client.list_objects(name, recursive=True))
        print(f"  对象数: {len(objects)}")

        for obj in objects:
            client.remove_object(name, obj.object_name)
            print(f"  已删除: {obj.object_name}")

        # 删除空桶
        client.remove_bucket(name)
        print(f"  桶已删除: {name}")

    print("\n[OK] MinIO 已清空 — 所有对象和桶已删除")


if __name__ == "__main__":
    clear_minio()