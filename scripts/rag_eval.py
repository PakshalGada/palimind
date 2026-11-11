#!/usr/bin/env python3
"""Local RAG retrieval benchmark.

Builds a throwaway workspace from ``benchmarks/rag/corpus``, indexes it, runs
every query in ``benchmarks/rag/golden.jsonl`` through the shared
``hybrid_search`` pipeline, and reports retrieval metrics.

Examples::

    python scripts/rag_eval.py --fake          # deterministic, no model needed
    python scripts/rag_eval.py --live          # real Ollama embeddings
    python scripts/rag_eval.py --live --rerank # include the cross-encoder

The report is written to ``benchmarks/rag/report-<timestamp>.json`` by default.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import re
import shutil
import sys
import tempfile
import time
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[1]
BACKEND_DIR = REPO_ROOT / "packages" / "backend"
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

_TOKEN_RE = re.compile(r"[a-z0-9]+")


def hash_embeddings(texts, _url, _model, root=None, expected_dim=None):  # noqa: ANN001
    """Deterministic bag-of-tokens embedding used by ``--fake``.

    It is not a semantic model; it exists so the harness, chunker, fusion and
    metrics can be exercised in CI without downloading or running Ollama.
    Shared words produce cosine similarity, which is enough to validate the
    plumbing and the lexical lane.
    """
    dim = int(expected_dim or 64)
    out: list[list[float]] = []
    for text in texts:
        vector = [0.0] * dim
        for token in _TOKEN_RE.findall(str(text).lower()):
            digest = hashlib.blake2b(token.encode("utf-8"), digest_size=8).hexdigest()
            vector[int(digest, 16) % dim] += 1.0
        norm = math.sqrt(sum(value * value for value in vector)) or 1.0
        out.append([value / norm for value in vector])
    return out


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument(
        "--fake",
        action="store_true",
        help="use deterministic hash embeddings (default; no model needed)",
    )
    mode.add_argument("--live", action="store_true", help="use real Ollama embeddings")
    parser.add_argument("--corpus", type=Path, default=REPO_ROOT / "benchmarks/rag/corpus")
    parser.add_argument("--golden", type=Path, default=REPO_ROOT / "benchmarks/rag/golden.jsonl")
    parser.add_argument("--out", type=Path, default=None)
    parser.add_argument("--model", default="bge-m3", help="embedding model for --live")
    parser.add_argument("--ollama-url", default="http://localhost:11434")
    parser.add_argument("--limit", type=int, default=10, help="passages requested per query")
    parser.add_argument("--top-k", type=int, default=10, help="ranking depth scored by nDCG")
    parser.add_argument("--budget", type=int, default=8000, help="context token budget")
    parser.add_argument("--rerank", action="store_true", help="enable cross-encoder reranking")
    parser.add_argument(
        "--fail-under",
        type=float,
        default=None,
        help="exit non-zero when mean Recall@5 is below this value",
    )
    return parser.parse_args()


def load_golden(path: Path) -> list[dict[str, Any]]:
    cases: list[dict[str, Any]] = []
    with path.open(encoding="utf-8") as handle:
        for line_number, line in enumerate(handle, start=1):
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            try:
                cases.append(json.loads(line))
            except json.JSONDecodeError as exc:
                raise SystemExit(f"{path}:{line_number}: invalid JSON ({exc})") from exc
    if not cases:
        raise SystemExit(f"No cases found in {path}")
    return cases


def check_ollama(url: str, model: str) -> None:
    try:
        import httpx
    except Exception as exc:  # pragma: no cover - httpx is a hard dependency
        raise SystemExit(f"httpx is required for --live: {exc}") from exc
    try:
        response = httpx.get(f"{url.rstrip('/')}/api/tags", timeout=5.0)
        response.raise_for_status()
        names = [str(item.get("name") or "") for item in response.json().get("models", [])]
    except Exception as exc:
        raise SystemExit(f"Ollama is not reachable at {url}: {exc}") from exc
    if model not in names and not any(name.startswith(f"{model}:") for name in names):
        raise SystemExit(
            f"Ollama at {url} does not list '{model}'. Installed: {', '.join(names[:10]) or '(none)'}"
        )


def main() -> int:
    args = parse_args()
    use_fake = not args.live

    from palimind.config import save_config
    from palimind.rag import evaluation
    from palimind.rag.indexing import initialize_index, update_index
    from palimind.rag.retrieve import clear_search_cache, hybrid_search

    if use_fake:
        model = "eval-hash"
        dim = 64
        from palimind.core import embedder
        from palimind.rag import indexing

        embedder.generate_embeddings_batch = hash_embeddings
        indexing.generate_embeddings_batch = hash_embeddings
    else:
        model = args.model
        check_ollama(args.ollama_url, model)
        try:
            from palimind.model_capabilities import infer_from_name

            dim = int(infer_from_name(model).embedding_dim or 1024)
        except Exception:
            dim = 1024
        # Load the embedding model before timing queries; otherwise the first
        # case includes model-load latency and skews the p95.
        try:
            from palimind.core.embedder import prewarm_model

            prewarm_model(args.ollama_url, model)
        except Exception:
            pass

    corpus_files = sorted(path for path in args.corpus.iterdir() if path.is_file())
    if not corpus_files:
        raise SystemExit(f"Corpus directory is empty: {args.corpus}")
    cases = load_golden(args.golden)

    timestamp = datetime.now(UTC).strftime("%Y%m%d-%H%M%S")
    out_path = args.out or REPO_ROOT / "benchmarks/rag" / f"report-{timestamp}.json"
    out_path.parent.mkdir(parents=True, exist_ok=True)

    report: dict[str, Any] = {
        "generated_at": datetime.now(UTC).isoformat(),
        "mode": "fake" if use_fake else "live",
        "model": model,
        "corpus": str(args.corpus),
        "golden": str(args.golden),
        "limit": args.limit,
        "rerank": bool(args.rerank),
        "cases": [],
    }

    scored: list[dict[str, Any]] = []
    abstentions: list[dict[str, Any]] = []

    with tempfile.TemporaryDirectory(prefix="palimind-rag-eval-") as tmp:
        workspace = Path(tmp) / "workspace"
        workspace.mkdir()
        for source in corpus_files:
            shutil.copy2(source, workspace / source.name)

        initialize_index(workspace)
        save_config(
            workspace,
            {
                "embed_model": model,
                "embed_dim": dim,
                "summarise": False,
                "summary_index": True,
                "build_graph": False,
                "rerank": bool(args.rerank),
                "rerank_opt_in": bool(args.rerank),
                "query_rewrite": False,
                "auto_reindex": False,
                "vector_quantization": "none",
                "child_chunk_size": 500,
                "child_chunk_overlap": 80,
            },
        )
        indexing_result = update_index(workspace)
        clear_search_cache(workspace)
        report["index"] = {
            "files": indexing_result.indexed_files,
            "chunks": indexing_result.chunks_indexed,
            "errors": [str(error) for error in indexing_result.file_errors],
            "dim": dim,
        }

        # Populate the FAISS in-memory cache and the embedder before timing.
        try:
            hybrid_search(
                workspace,
                "warmup",
                limit=1,
                ollama_url=args.ollama_url if not use_fake else "http://fake",
                embed_model=model,
                rerank_enabled=False,
                query_rewrite_enabled=False,
                context_token_budget=args.budget,
            )
        except Exception:
            pass

        for case in cases:
            query = str(case.get("query") or "")
            expected = list(case.get("expected") or [])
            started = time.perf_counter()
            try:
                result = hybrid_search(
                    workspace,
                    query,
                    limit=args.limit,
                    ollama_url=args.ollama_url if not use_fake else "http://fake",
                    embed_model=model,
                    rerank_enabled=bool(args.rerank),
                    query_rewrite_enabled=False,
                    context_token_budget=args.budget,
                    summary_search=True,
                )
                results = list(result.get("results") or [])
                errors = list(result.get("errors") or [])
                diagnostics = result.get("diagnostics") or {}
            except Exception as exc:  # noqa: BLE001 - one case must not abort the run
                results = []
                errors = [f"{type(exc).__name__}: {exc}"]
                diagnostics = {}
            latency_ms = round((time.perf_counter() - started) * 1000, 1)

            metrics = evaluation.evaluate_case(results, expected, ndcg_k=args.top_k)
            phrases = evaluation.phrase_hit(results, list(case.get("phrases") or []))
            record = {
                "id": case.get("id"),
                "query": query,
                "expected": expected,
                "retrieved": [
                    {
                        "file": item.get("file_path"),
                        "section": item.get("section_title") or item.get("main_section") or "",
                        "page": item.get("page_number"),
                        "score": item.get("relevance_score") or item.get("rerank_score"),
                        "retrieval": item.get("search_type", ""),
                        "preview": (item.get("content") or "")[:200],
                    }
                    for item in results[: args.top_k]
                ],
                "metrics": metrics,
                "phrase_hit": round(phrases, 4),
                "latency_ms": latency_ms,
                "errors": errors,
                "diagnostics": diagnostics,
            }
            if expected:
                record["passed"] = bool(
                    metrics.get("recall@5", 0.0) >= 1.0 and phrases >= 1.0
                )
                scored.append(record)
            else:
                record["passed"] = None
                abstentions.append(record)
            report["cases"].append(record)

    report["summary"] = evaluation.aggregate(scored)
    report["abstain_cases"] = len(abstentions)
    out_path.write_text(json.dumps(report, indent=2), encoding="utf-8")

    print(
        f"RAG eval — mode={report['mode']} model={model} "
        f"files={report['index']['files']} chunks={report['index']['chunks']}"
    )
    print(
        f"{'case':<22} {'R@5':>5} {'MRR':>5} {'nDCG':>5} {'phrase':>6} {'ms':>8}  top"
    )
    for record in report["cases"]:
        metrics = record["metrics"]
        top = (record["retrieved"][0]["file"] if record["retrieved"] else "-") or "-"
        section = record["retrieved"][0]["section"] if record["retrieved"] else ""
        top_label = f"{top} {section}".strip()
        if not record["expected"]:
            print(
                f"{str(record['id']):<22} {'abstain':>5} "
                f"{'-':>5} {'-':>5} {'-':>6} "
                f"{record['latency_ms']:>8.1f}  {top_label[:46]}"
            )
            continue
        print(
            f"{str(record['id']):<22} "
            f"{metrics.get('recall@5', 0.0):>5.2f} "
            f"{metrics.get('mrr', 0.0):>5.2f} "
            f"{metrics.get('ndcg@10', 0.0):>5.2f} "
            f"{record['phrase_hit']:>6.2f} "
            f"{record['latency_ms']:>8.1f}  {top_label[:46]}"
        )
    summary = report["summary"]
    print(
        f"\nmean: Recall@5={summary.get('recall@5', 0.0):.3f} "
        f"Recall@10={summary.get('recall@10', 0.0):.3f} "
        f"MRR={summary.get('mrr', 0.0):.3f} "
        f"nDCG@10={summary.get('ndcg@10', 0.0):.3f} "
        f"phrase={summary.get('phrase_hit', 0.0):.3f}"
    )
    print(
        f"latency: p50={summary.get('latency_ms_p50', 0.0):.0f}ms "
        f"p95={summary.get('latency_ms_p95', 0.0):.0f}ms "
        f"abstain cases={report['abstain_cases']}"
    )
    print(f"report: {out_path}")

    if args.fail_under is not None and summary.get("recall@5", 0.0) < args.fail_under:
        print(
            f"FAIL: Recall@5 {summary.get('recall@5', 0.0):.3f} "
            f"< {args.fail_under:.3f}",
            file=sys.stderr,
        )
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
