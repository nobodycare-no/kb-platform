"""RAGAS 量化评估（对齐《知识库的评估与优化》课件流程）。

step_1 初始化评估组件（LLM=Qwen3-8B@vLLM, Embeddings=bge-m3@AutoDL, 五指标）
step_2 加载测试数据（golden.jsonl: question/user/ground_truth）
step_3 运行 RAG pipeline（真实 /api/ai/chat/stream，采集 answer+contexts）
step_4 构建 Ragas Dataset
step_5 ragas.evaluate() 计算五指标（raise_exceptions=False）
step_6 导出 eval_results.csv(utf-8-sig+平均值行) 与 bad_cases.csv(<0.5 或 NaN)

运行：conda activate ragas && python run_ragas_metrics.py [--backend URL]
"""
import argparse
import asyncio
import json
import os
import sys
import time

os.environ.setdefault("NO_PROXY", "127.0.0.1,localhost,.seetacloud.com")
os.environ.setdefault("no_proxy", "127.0.0.1,localhost,.seetacloud.com")

import httpx  # noqa: E402
import pandas as pd  # noqa: E402
from datasets import Dataset  # noqa: E402
from langchain_core.embeddings import Embeddings  # noqa: E402
from ragas import evaluate  # noqa: E402
from ragas.embeddings import LangchainEmbeddingsWrapper  # noqa: E402
from ragas.llms import LangchainLLMWrapper  # noqa: E402
from ragas.metrics import (  # noqa: E402
    answer_correctness,
    answer_relevancy,
    context_precision,
    context_recall,
    faithfulness,
)

HERE = os.path.dirname(__file__)


# ---------- BGE-M3 嵌入适配（autodl_bge 协议，dense only） ----------
class ProjectBGEEmbeddings(Embeddings):
    """把 AutoDL bge-m3 服务的 dense 向量适配为 LangChain Embeddings。"""

    def __init__(self, base_url: str):
        self.base = base_url.rstrip("/")
        self._client = httpx.Client(verify=True, timeout=60)

    def _embed(self, texts):
        resp = self._client.post(f"{self.base}/embeddings",
                                 json={"embedding_documents": list(texts)})
        resp.raise_for_status()
        return [list(map(float, v)) for v in resp.json()["dense"]]

    def embed_documents(self, texts):
        return [] if not texts else self._embed(texts)

    def embed_query(self, text):
        return self.embed_documents([text])[0]


def step_1_init_eval_components(settings: dict):
    from langchain_openai import ChatOpenAI
    from ragas.llms import LangchainLLMWrapper

    judge = ChatOpenAI(
        model=settings["llm_model"],
        openai_api_key=settings["llm_key"],
        openai_api_base=settings["llm_base"],
        temperature=0,
        model_kwargs={"extra_body": {"chat_template_kwargs": {"enable_thinking": False}}},
    )
    ragas_llm = LangchainLLMWrapper(judge)
    embeddings = LangchainEmbeddingsWrapper(
        ProjectBGEEmbeddings(settings["embedding_base"]))
    metrics = [faithfulness, answer_relevancy, context_precision,
               context_recall, answer_correctness]
    return ragas_llm, embeddings, metrics


def step_2_load_test_samples(path: str):
    """加载黄金集；拒答预期行不进入 RAGAS（空答案/空参考会污染指标），行为层已单独验证。"""
    items = []
    skipped = 0
    with open(path, encoding="utf-8") as f:
        for line in f:
            if not line.strip():
                continue
            obj = json.loads(line)
            if obj.get("expect_refusal"):
                skipped += 1
                continue
            items.append(obj)
    print(f"[step_2] 加载 {len(items)} 条黄金样本（跳过拒答预期 {skipped} 条）")
    return items


def step_3_run_pipeline(backend: str, items) -> dict:
    answers, contexts = [], []
    for i, item in enumerate(items, 1):
        tok = httpx.post(f"{backend}/api/auth/login",
                         json={"username": item.get("user", "admin"),
                               "password": "Abc12345!"}, timeout=15
                         ).json()["data"]["access_token"]
        out = {"answer": "", "sources": []}
        with httpx.stream("POST", f"{backend}/api/ai/chat/stream",
                          headers={"Authorization": f"Bearer {tok}"},
                          json={"question": item["question"]}, timeout=180) as r:
            assert r.status_code == 200, f"#{i} HTTP {r.status_code}"
            buf = ""
            for chunk in r.iter_bytes():
                buf += chunk.decode("utf-8")
        for block in buf.split("\n\n"):
            ev, data = None, {}
            for line in block.strip().splitlines():
                if line.startswith("event:"):
                    ev = line[6:].strip()
                elif line.startswith("data:"):
                    data = json.loads(line[5:].strip())
            if ev == "delta":
                out["answer"] += data["delta_text"]
            elif ev == "sources":
                out["sources"] = data["items"]
        ctx = [(s.get("title", "") + "\n" + s.get("content", "")).strip()
               for s in out["sources"]]
        answers.append(out["answer"])
        contexts.append(ctx)
        print(f"[step_3] ({i}/{len(items)}) ctx={len(ctx)} ans={len(out['answer'])}字")
    return {"answers": answers, "contexts": contexts}


def step_4_build_dataset(items, results) -> Dataset:
    # contexts 截断至每片 1200 字，防止 judge 超出 8192 上下文
    capped = [[c[:1200] for c in ctx_list] for ctx_list in results["contexts"]]
    return Dataset.from_dict({
        "question": [i["question"] for i in items],
        "answer": results["answers"],
        "contexts": capped,
        "ground_truth": [i["ground_truth"] for i in items],
    })


def step_5_run_ragas(dataset, metrics, llm, embeddings):
    print("[step_5] RAGAS evaluate() 计算中（judge=qwen3-8b）...")
    return evaluate(dataset=dataset, metrics=metrics, llm=llm,
                    embeddings=embeddings, raise_exceptions=False)


def step_6_export(results, metrics) -> None:
    df = results.to_pandas()
    metric_names = [m.name for m in metrics]
    avg = {c: "" for c in df.columns}
    avg[df.columns[0]] = "平均值"
    for name in metric_names:
        if name in df.columns:
            avg[name] = pd.to_numeric(df[name], errors="coerce").mean()
    df_out = pd.concat([df, pd.DataFrame([avg])], ignore_index=True)
    out_csv = os.path.join(HERE, f"ragas_eval_results_{time.strftime('%Y%m%d-%H%M%S')}.csv")
    df_out.to_csv(out_csv, index=False, encoding="utf-8-sig")
    print(f"[step_6] 明细+平均值行已写入 {out_csv}")

    bad_col = "answer_correctness"
    if bad_col in df.columns:
        bad = df[pd.to_numeric(df[bad_col], errors="coerce").lt(0.5)
                 | pd.to_numeric(df[bad_col], errors="coerce").isna()]
        bad_path = os.path.join(HERE, f"bad_cases_{time.strftime('%Y%m%d-%H%M%S')}.csv")
        bad.to_csv(bad_path, index=False, encoding="utf-8-sig")
        print(f"[step_6] Bad cases(answer_correctness<0.5 或 NaN)：{len(bad)} 条 → {bad_path}")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--backend", default=os.environ.get("EVAL_BACKEND", "http://127.0.0.1:8081"))
    args = ap.parse_args()

    env = {}
    for line in open(os.path.join(os.path.dirname(os.path.dirname(HERE)), ".env"), encoding="utf-8"):
        line = line.strip()
        if line and not line.startswith("#") and "=" in line:
            k, v = line.split("=", 1)
            env[k] = v

    settings = {
        "llm_base": env["LLM_BASE_URL"].rstrip("/"),
        "llm_key": env["LLM_API_KEY"],
        "llm_model": env.get("LLM_MODEL", "qwen3-8b"),
        "embedding_base": env["EMBEDDING_BASE_URL"].rstrip("/"),
    }

    llm, embeddings, metrics = step_1_init_eval_components(settings)
    items = step_2_load_test_samples(os.path.join(HERE, "golden.jsonl"))
    results = step_3_run_pipeline(args.backend, items)
    dataset = step_4_build_dataset(items, results)
    ragas_results = step_5_run_ragas(dataset, metrics, llm, embeddings)
    step_6_export(ragas_results, metrics)


if __name__ == "__main__":
    main()
