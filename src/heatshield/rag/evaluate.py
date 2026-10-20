"""Evaluate the RAG Insight Agent (citations and "I don't know" behaviour).

1. Threshold tuning on the **dev** questions only: grid search over the
   minimum retrieval score, minimum query coverage and allowed missing key
   terms, maximising balanced accuracy of the answer/refuse decision
   (ties -> fewer false refusals). Saved to ``data/rag/thresholds.json``.
2. Report on the held-out **test** questions (and on all, for reference):
   * retrieval hit@1 / hit@3 - a passage from an expected document page,
   * citation precision - share of cited passages on an expected page,
   * keyword hit rate - the answer contains an expected fact,
   * correct refusals on unsupported questions / false refusals on answerable ones,
   * data questions - answer cites the expected Gold row id(s).

Usage: ``python -m heatshield.rag.evaluate`` (= make -C src rag-eval)
"""
from __future__ import annotations

import itertools
import json
import sys

import numpy as np

from heatshield import config
from heatshield.rag.agent import DEFAULT_THRESHOLDS, THRESHOLDS_FILE, DocumentIndex, HeatShieldAssistant, decide

QUESTIONS = config.ROOT / "eval" / "rag_questions.json"


def _on_expected(chunk_or_cit: dict, expect) -> bool:
    return any(chunk_or_cit["doc_id"] == d and chunk_or_cit["page"] in pages for d, pages in expect)


def tune(index: DocumentIndex, qs: dict) -> dict:
    dev_a = [q for q in qs["answerable"] if q["split"] == "dev"]
    dev_u = [q for q in qs["unsupported"] if q["split"] == "dev"]
    sig = lambda q: index.search(q["q"], 5)[0]
    a_sig, u_sig = [sig(q) for q in dev_a], [sig(q) for q in dev_u]
    best = None
    grid = itertools.product(np.round(np.arange(0.02, 0.13, 0.01), 2), np.round(np.arange(0.06, 0.31, 0.01), 2), [0, 1, 2])
    for floor, ms, mk in grid:
        if ms < floor:
            continue
        th = {"floor_score": float(floor), "min_score": float(ms), "max_missing_key_terms": mk}
        tpr = np.mean([decide(p, th) for p in a_sig])          # answerable answered
        tnr = np.mean([not decide(p, th) for p in u_sig])      # unsupported refused
        key = (round((tpr + tnr) / 2, 4), tpr, -floor, -ms)    # balanced acc, then fewer false refusals
        if best is None or key > best[0]:
            best = (key, th)
    th = best[1]
    th["tuned_on"] = f"dev split: {len(dev_a)} answerable + {len(dev_u)} unsupported questions"
    th["dev_balanced_accuracy"] = best[0][0]
    return th


def score(assistant: HeatShieldAssistant, qs: dict, split: str | None) -> tuple[dict, list]:
    sel = lambda items: [q for q in items if split is None or q["split"] == split]
    rows, A, U, D = [], sel(qs["answerable"]), sel(qs["unsupported"]), sel(qs["data"])
    hit1 = hit3 = kw = answered = 0
    cit_good = cit_all = 0
    for q in A:
        hits = assistant.index.search(q["q"], 5)
        h1, h3 = _on_expected(hits[0].chunk, q["expect"]), any(_on_expected(h.chunk, q["expect"]) for h in hits[:3])
        ans = assistant.answer_from_documents(q["q"])
        good = [c for c in ans.citations if _on_expected(c, q["expect"])]
        k = any(w.lower() in ans.text.lower() for w in q["keywords"]) if ans.supported else False
        hit1 += h1; hit3 += h3; kw += k; answered += ans.supported
        cit_good += len(good); cit_all += len(ans.citations)
        rows.append({"id": q["id"], "split": q["split"], "type": "answerable", "question": q["q"], "answered": ans.supported,
                     "hit@1": h1, "hit@3": h3, "keyword_hit": k, "citations": [c["chunk_id"] for c in ans.citations],
                     "citations_on_expected_page": len(good)})
    refused = 0
    for q in U:
        ans = assistant.answer_from_documents(q["q"])
        refused += not ans.supported
        rows.append({"id": q["id"], "split": q["split"], "type": "unsupported", "question": q["q"],
                     "refused": not ans.supported, "top": ans.retrieval[0] if ans.retrieval else None})
    data_ok = 0
    for q in D:
        ans = assistant.ask(q["q"])
        ids = [c["row_id"] for c in ans.citations if c["type"] == "gold_row"]
        if "expect_row_ids" in q:
            ok = all(r in ids for r in q["expect_row_ids"])
        else:
            ok = all(any(i.startswith(p) for i in ids) for p in q["expect_row_prefix"])
        data_ok += ok
        rows.append({"id": q["id"], "split": q["split"], "type": "data", "question": q["q"], "cited_rows": ids, "correct": ok})
    n = lambda x: max(1, len(x))
    metrics = {
        "answerable_questions": len(A), "unsupported_questions": len(U), "data_questions": len(D),
        "retrieval_hit_at_1": hit1 / n(A), "retrieval_hit_at_3": hit3 / n(A),
        "answer_rate_on_answerable": answered / n(A), "false_refusal_rate": 1 - answered / n(A),
        "keyword_hit_rate": kw / n(A), "citation_precision": cit_good / max(1, cit_all),
        "correct_refusal_rate_on_unsupported": refused / n(U),
        "idk_balanced_accuracy": (answered / n(A) + refused / n(U)) / 2,
        "data_questions_correct_row_ids": data_ok / n(D),
    }
    return metrics, rows


def to_markdown(th: dict, res: dict) -> str:
    keys = [("retrieval_hit_at_1", "Retrieval hit@1 (expected page ranked first)"),
            ("retrieval_hit_at_3", "Retrieval hit@3"),
            ("citation_precision", "Citation precision (cited passage on an expected page)"),
            ("keyword_hit_rate", "Answer contains the expected fact"),
            ("answer_rate_on_answerable", "Answerable questions answered"),
            ("false_refusal_rate", "False \"I don't know\" on answerable"),
            ("correct_refusal_rate_on_unsupported", "Correct \"I don't know\" on unsupported"),
            ("idk_balanced_accuracy", "Answer/refuse balanced accuracy"),
            ("data_questions_correct_row_ids", "Data questions citing the right Gold row")]
    L = ["# RAG Insight Agent — evaluation", "",
         "*Generated by `make -C src rag-eval` (extractive answers, no language model, fully reproducible).* "
         f"Question set: `eval/rag_questions.json`. Thresholds tuned on the dev split only: "
         f"`floor_score={th['floor_score']}`, `min_score={th['min_score']}`, "
         f"`max_missing_key_terms={th['max_missing_key_terms']}` (answer if no specific query term is missing from the "
         "retrieved passages, or if at most that many are missing and the retrieval score reaches `min_score`).", "",
         "| Metric | Test (held out) | Dev | All |", "|---|---|---|---|"]
    for k, label in keys:
        L.append(f"| {label} | {res['test']['metrics'][k]:.0%} | {res['dev']['metrics'][k]:.0%} | {res['all']['metrics'][k]:.0%} |")
    m = res["test"]["metrics"]
    L += ["", f"Test split size: {m['answerable_questions']} answerable, {m['unsupported_questions']} unsupported, "
          f"{m['data_questions']} data questions — small, so each question moves a rate by several points.", "",
          "## Per-question results (all splits)", "", "| ID | Split | Type | Question | Outcome |", "|---|---|---|---|---|"]
    for r in res["all"]["rows"]:
        if r["type"] == "answerable":
            out = ("answered" if r["answered"] else "**false refusal**") + f", hit@3={'yes' if r['hit@3'] else 'no'}, fact={'yes' if r['keyword_hit'] else 'no'}"
        elif r["type"] == "unsupported":
            out = "refused ✓" if r["refused"] else "**answered (should refuse)**"
        else:
            out = ("✓ " if r["correct"] else "✗ ") + ", ".join(r["cited_rows"])
        L.append(f"| {r['id']} | {r['split']} | {r['type']} | {r['question']} | {out} |")
    L += ["", "## Notes", "",
          "* Refusal is decided before any text is generated, from retrieval signals only, so an unsupported question "
          "never produces an answer.",
          "* Honesty note: the decision *rule* and the synonym list were refined while looking at failures across all "
          "questions; only the numeric thresholds are fitted strictly on dev. Treat test numbers as somewhat optimistic.",
          ""]
    return "\n".join(L)


def main() -> int:
    qs = json.loads(QUESTIONS.read_text(encoding="utf-8"))
    index = DocumentIndex.load()
    th = tune(index, qs)
    THRESHOLDS_FILE.parent.mkdir(parents=True, exist_ok=True)
    THRESHOLDS_FILE.write_text(json.dumps(th, indent=2), encoding="utf-8")
    assistant = HeatShieldAssistant(index=index, thresholds={**DEFAULT_THRESHOLDS, **th})
    res = {}
    for split in ("dev", "test", None):
        metrics, rows = score(assistant, qs, split)
        res[split or "all"] = {"metrics": metrics, "rows": rows}
    config.REPORTS.mkdir(parents=True, exist_ok=True)
    (config.REPORTS / "rag_evaluation.json").write_text(json.dumps({"thresholds": th, **res}, indent=2, default=str),
                                                         encoding="utf-8")
    (config.REPORTS / "rag_evaluation.md").write_text(to_markdown(th, res), encoding="utf-8")
    print("thresholds:", {k: th[k] for k in ("floor_score", "min_score", "max_missing_key_terms")})
    for split in ("dev", "test"):
        m = res[split]["metrics"]
        print(f"{split}: hit@3 {m['retrieval_hit_at_3']:.0%} | citation precision {m['citation_precision']:.0%} | "
              f"fact {m['keyword_hit_rate']:.0%} | false refusals {m['false_refusal_rate']:.0%} | "
              f"correct refusals {m['correct_refusal_rate_on_unsupported']:.0%} | data {m['data_questions_correct_row_ids']:.0%}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
