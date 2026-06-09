from __future__ import annotations

import json

from kb_mvp.models import RawDocument
from kb_mvp.pipeline import InMemoryKnowledgeBase


def main() -> None:
    kb = InMemoryKnowledgeBase(max_depth=2)

    root_doc = RawDocument(
        doc_id="doc_root",
        title="用户手册",
        source_type="markdown",
        source_uri="memory://user-manual.md",
        content="""# 上传知识文档

用户可以在知识库页面上传文档。上传后，页面会展示解析状态。

| 状态 | 说明 | 用户操作 |
| --- | --- | --- |
| 处理中 | 系统正在解析文档 | 等待处理完成 |
| 成功 | 文档已经进入知识库 | 可以开始检索 |
| 失败 | 需要查看失败原因 | 修正后重新上传 |

![上传状态图](https://example.com/upload-status.png)

视频说明：https://example.com/upload-demo.mp4

更多说明见：[嵌入说明](https://example.com/embedded-doc.md)
""",
    )

    embedded_docs = {
        "https://example.com/embedded-doc.md": """# 嵌入说明

解析失败通常与文件格式、文件大小或权限有关。用户应先查看失败原因，再重新上传修正后的文档。
""",
    }

    ingest_result = kb.ingest([root_doc], embedded_content_by_uri=embedded_docs)
    search_result = kb.search("上传以后怎么知道进库成功了？", top_k=3)

    print("INGEST RESULT")
    print(json.dumps(ingest_result, ensure_ascii=False, indent=2))
    print()
    print("SEARCH RESULT")
    print(json.dumps(search_result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
