from __future__ import annotations

import re


def tokenize(text: str) -> list[str]:
    """对中英文混合文本做本地 MVP 分词。

    参数:
        text: 待分词的原始文本。

    返回:
        一个 token 列表。英文和数字按连续单词保留；中文会生成整段、单字、
        二字词和三字词，用来提高短口语查询与较长陈述型知识块之间的重合率。

    说明:
        这是为了最小内存版检索链路准备的轻量实现，不追求中文分词精度。
        正式版本可以替换为专业分词器或直接使用 Milvus/搜索引擎的稀疏检索。
    """

    lower = text.lower()
    tokens = re.findall(r"[a-z0-9_]+", lower)
    cjk_runs = re.findall(r"[\u4e00-\u9fff]+", lower)
    for run in cjk_runs:
        tokens.extend(run)
        chars = list(run)
        tokens.extend(chars)
        for size in (2, 3):
            tokens.extend("".join(chars[index : index + size]) for index in range(len(chars) - size + 1))
    return tokens
