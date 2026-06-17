"""验证 OpenAI SDK 调用火山引擎方舟模型。"""
import os
from openai import OpenAI

api_key = "ark-140d7c0e-0647-4ffa-aab8-8b9d09764caa-6fee4"
if not api_key:
    raise RuntimeError("请设置环境变量 ARK_API_KEY")

client = OpenAI(
    base_url="https://ark.cn-beijing.volces.com/api/v3",
    api_key=api_key,
)

response = client.chat.completions.create(
    model="doubao-seed-2-0-pro-260215",
    messages=[
        {"role": "user", "content": "你是谁？"},
    ],
)
print(response.choices[0].message.content)
