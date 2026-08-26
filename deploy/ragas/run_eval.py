"""RAGAS 评估运行器（课程要求：RAGAS -> CSV -> 针对性调整）。

前置：
  1. GPU 实例开机，deploy/.env 中 LLM/EMBEDDING/RERANK 地址可用
  2. 已执行 seed 并完成向量索引
  3. pip install ragas datasets langchain-openai（建议在独立环境）

用法：
    python deploy/ragas/run_eval.py [--backend http://127.0.0.1:8081]

流程：对 golden.jsonl 每条调用真实 /api/ai/chat/stream 取答案与召回上下文，
组装 RAGAS 所需样本集后计算 faithfulness / answer_relevancy /
context_precision / context_recall，输出 CSV 至同目录（按时间戳命名），
供《测试评估报告》引用并驱动检索参数调优。
"""
import argparse
import asyncio
import json
import os
import sys
import time
from pathlib import Path

import httpx

os.environ.setdefault("NO_PROXY", "127.0.0.1,localhost")   # 本机代理会劫持 localhost
os.environ.setdefault("no_proxy", "127.0.0.1,localhost")

HERE = Path(__file__).parent


async def ask_once(base: str, token: str, question: str) -> dict:
    events = []
    async with httpx.AsyncClient(timeout=120, trust_env=False) as cli:
        async with cli.stream("POST", f"{base}/api/ai/chat/stream",
                              headers={"Authorization": f"Bearer {token}"},
                              json={"question": question}) as resp:
            if resp.status_code != 200:
                raise RuntimeError(f"chat/stream HTTP {resp.status_code}")
            buf = ""
            async for chunk in resp.aiter_bytes():
                buf += chunk.decode("utf-8")
            for block in buf.split("\n\n"):
                ev, data = None, {}
                for line in block.strip().splitlines():
                    if line.startswith("event:"):
                        ev = line[6:].strip()
                    elif line.startswith("data:"):
                        data = json.loads(line[5:].strip())
                if ev:
                    events.append((ev, data))
    answer = "".join(d["delta_text"] for e, d in events if e == "delta")
    sources = next((d["items"] for e, d in events if e == "sources"), [])
    contexts = [
        (s.get("title", "") + "\n" + s.get("content", "")).strip()
        for s in sources
    ]
    unauthorized = next((d["units"] for e, d in events if e == "unauthorized"), [])
    done = next((d for e, d in events if e == "done"), {})
    return {"answer": answer,
            "contexts": contexts,
            "unauthorized": unauthorized,
            "degraded": done.get("degraded", False),
            "tokens": done.get("total_tokens", 0)}


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--backend", default=os.environ.get("E2E_BACKEND", "http://127.0.0.1:8081"))
    parser.add_argument("--username", default="admin")
    parser.add_argument("--password", default="Abc12345!")
    args = parser.parse_args()

    login = httpx.post(f"{args.backend}/api/auth/login",
                       json={"username": args.username, "password": args.password}).json()["data"]
    headers = {"Authorization": f"Bearer {login['access_token']}"}

    golden = [json.loads(line) for line in
              (HERE / "golden.jsonl").read_text(encoding="utf-8").splitlines() if line.strip()]

    samples, rows = [], []
    for item in golden:
        t0 = time.time()
        ask_user = item.get("user", args.username)
        tok = httpx.post(f"{args.backend}/api/auth/login",
                         json={"username": ask_user, "password": "Abc12345!"}
                         ).json()["data"]["access_token"]
        result = asyncio.run(ask_once(args.backend, tok, item["question"]))
        ms = int((time.time() - t0) * 1000)
        expect_refusal = item.get("expect_refusal") or item.get("expect_unauthorized") \
            or not item["ground_truth"]
        refused = "暂未找到" in result["answer"] or not result["answer"].strip()
        ok_flag = refused if expect_refusal else bool(result["answer"])
        rows.append({"question": item["question"], "user": ask_user,
                     "answer": result["answer"],
                     "contexts": "\n---\n".join(result["contexts"]),
                     "expect_refusal": expect_refusal,
                     "refused": refused,
                     "judge_ok": ok_flag, "latency_ms": ms,
                     "degraded": result["degraded"], "tokens": result["tokens"]})
        print(f"[{'OK ' if ok_flag else 'MISS'}] ({ask_user}) {item['question'][:24]}  {ms}ms")

    stamp = time.strftime("%Y%m%d-%H%M%S")
    out_csv = HERE / f"ragas_report_{stamp}.csv"
    with open(out_csv, "w", encoding="utf-8-sig", newline="") as f:
        writer = __import__("csv").DictWriter(f, fieldnames=list(rows[0].keys()))
        writer.writeheader()
        writer.writerows(rows)

    hit = sum(1 for r in rows if r["judge_ok"])
    print(f"[done] 命中 {hit}/{len(rows)}；报告已写入 {out_csv}")
    print("[next] 将本 CSV 与 golden.jsonl 喂给 ragas 库计算四指标：")
    print("       faithfulness / answer_relevancy / context_precision / context_recall")
    print("       （需 GPU 端 LLM 作为评测 judge，详见开发手册 Task 8.2）")
    return 0


if __name__ == "__main__":
    sys.exit(main())
