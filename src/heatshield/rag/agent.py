"""HeatShield RAG Insight Agent.

Answers questions from two kinds of evidence and cites both:

* **Official documents** (NDMA advisory, PDMA Sindh alert incl. PMD alert,
  PDMA Sindh SOPs) - cited as ``[n] document, page, section``.
* **Gold data** (observed daily heat index, model forecasts, NWP forecast) -
  cited by Gold-table ``row_id`` so every number can be traced.

Unsupported questions get an explicit "I don't know" instead of a guess. The
decision is made *before* any text is generated, from two retrieval signals
(best similarity score and query-term coverage of the best chunk), with
thresholds chosen on the development half of the evaluation set only.

Answers are extractive: selected sentences, verbatim, each with its
citation. No language model is used, so the assistant works offline and
cannot invent facts.
"""
from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from datetime import timedelta

import numpy as np
import pandas as pd
from sklearn.feature_extraction.text import ENGLISH_STOP_WORDS, TfidfVectorizer

from heatshield import config
from heatshield.heat_index import risk_level

IDK = "I don't know — the official documents available to HeatShield do not answer this question."
THRESHOLDS_FILE = config.DATA / "rag" / "thresholds.json"
DEFAULT_THRESHOLDS = {"floor_score": 0.06, "min_score": 0.13, "max_missing_key_terms": 1}
# Words too generic to decide whether the documents cover a question.
GENERIC = {"heat", "heatwave", "heatwaves", "hot", "weather", "temperature", "temperatures", "day", "days", "time",
           "way", "ways", "best", "tips", "safe", "safety", "stay", "keep", "help", "need", "important", "role",
           "work", "make", "dangerous", "conditions", "during", "summer", "high", "extreme", "risk", "measures",
           # question-framing words: they describe the kind of answer, not its topic
           "kind", "kinds", "type", "types", "list", "lists", "thing", "things", "much", "many", "carry", "warned",
           "warn", "degree", "degrees", "sops", "sop", "guidelines", "mention", "mentions", "include", "includes",
           "feel", "feeling", "get", "getting", "go", "going"}

STOP = set(ENGLISH_STOP_WORDS) | {"according", "official", "documents", "document", "say", "says", "tell",
                                  "pakistan", "does", "did", "should", "people", "advice", "advised", "recommended",
                                  "recommend", "happens", "mentioned", "described", "per", "please", "know", "explain"}
SYNONYMS = {
    "heatstroke": "heatstroke heat stroke", "stroke": "heatstroke stroke", "ors": "ors oral rehydration salts",
    "kids": "children", "child": "children", "elderly": "elderly senior citizens", "old": "elderly senior",
    "pregnant": "pregnant women", "water": "water hydrated hydration", "drink": "drink water hydrated",
    "hydrate": "hydrated hydration water", "school": "school schools educational students",
    "workers": "workers labour labor outdoor", "labour": "labour labor workers", "hospital": "hospitals health",
    "electricity": "power supply energy load", "power": "power supply energy", "clothes": "clothing",
    "wear": "clothing wear", "home": "home indoor homes", "house": "home indoor", "car": "vehicle",
    "travel": "travel vehicle", "symptoms": "symptoms dizziness nausea weakness", "sun": "sun sunlight",
    "deaths": "deaths fatalities", "died": "deaths fatalities", "cases": "cases treated",
    "cool": "cool cooling", "cooler": "cool cooling indoor heat reduce", "cooling": "cooling cool",
    "illness": "illnesses heat exhaustion heatstroke dehydration", "illnesses": "illnesses heat exhaustion heatstroke dehydration",
    "carry": "equipped supplies", "equipment": "equipped supplies", "sick": "illnesses symptoms",
    "forecast": "forecast weather forecast maximum temp", "hottest": "highest temperatures",
    "dizzy": "dizziness symptoms", "nauseous": "nausea symptoms", "weak": "weakness symptoms",
    "faint": "dizziness weakness symptoms", "headache": "symptoms", "sweat": "sweating", "sweating": "sweating",
}
CITY_ALIASES = {"karachi": "karachi", "khi": "karachi", "lahore": "lahore", "lhr": "lahore",
                "jacobabad": "jacobabad", "jacob abad": "jacobabad"}
DATA_WORDS = re.compile(r"\b(today|tonight|tomorrow|day after|forecast|right now|now|current|currently|this week|"
                        r"next (?:\d|few|three|3) days|heat index|risk level|risk|feels like|temperature|hot(?:test)?|"
                        r"on \d{4}-\d{2}-\d{2}|yesterday)\b", re.I)
GUIDANCE_WORDS = re.compile(r"\b(what should|how (?:can|do|should)|precaution|safe|protect|advice|tips?|avoid|guidance|do i)\b", re.I)


def _tokens(text: str) -> list[str]:
    return [t for t in re.findall(r"[a-z0-9]+", text.lower()) if t not in STOP and len(t) > 1]


def _stem(t: str) -> str:
    """Crude stemmer: strip a common suffix, then keep 5 characters."""
    for suf in ("ness", "ing", "ed", "es", "ly", "s"):
        if len(t) > len(suf) + 3 and t.endswith(suf):
            t = t[: -len(suf)]
            break
    return t[:5]


def expand(query: str) -> str:
    extra = [SYNONYMS[t] for t in _tokens(query) if t in SYNONYMS]
    return query + " " + " ".join(extra)


# ======================================================================== index
@dataclass
class Passage:
    chunk: dict
    score: float
    coverage: float
    missing_key_terms: list = field(default_factory=list)


class DocumentIndex:
    def __init__(self, chunks: list[dict]):
        self.chunks = chunks
        texts = [c.get("search_text", c["text"]) for c in chunks]
        self.word = TfidfVectorizer(ngram_range=(1, 2), sublinear_tf=True, stop_words=list(STOP), min_df=1)
        self.char = TfidfVectorizer(analyzer="char_wb", ngram_range=(3, 5), sublinear_tf=True, min_df=1)
        self.Wm = self.word.fit_transform(texts)
        self.Cm = self.char.fit_transform(texts)
        self.stems = [{_stem(t) for t in _tokens(x)} for x in texts]
        df: dict[str, int] = {}
        for st in self.stems:
            for t in st:
                df[t] = df.get(t, 0) + 1
        self.doc_freq, self.n_chunks = df, len(chunks)

    def key_terms(self, query: str) -> set[str]:
        """Specific query terms: absent from the corpus or present in <= 8 % of chunks."""
        out = set()
        for t in _tokens(query):
            if t.isdigit():
                if len(t) == 4 and _stem(t) not in self.doc_freq:   # a year the documents never mention
                    out.add(t)
                continue
            if t in GENERIC or t in SYNONYMS:
                continue
            if self.doc_freq.get(_stem(t), 0) <= 0.08 * self.n_chunks:
                out.add(_stem(t))
        return out

    @classmethod
    def load(cls) -> "DocumentIndex":
        from heatshield.rag.ingest import CHUNKS, ensure_index
        ensure_index()
        chunks = [json.loads(line) for line in CHUNKS.read_text(encoding="utf-8").splitlines() if line.strip()]
        return cls(chunks)

    def search(self, query: str, k: int = 5) -> list[Passage]:
        q = expand(query)
        s = 0.6 * (self.Wm @ self.word.transform([q]).T).toarray().ravel() \
            + 0.4 * (self.Cm @ self.char.transform([q]).T).toarray().ravel()
        q_stems = {_stem(t) for t in _tokens(query)}
        order = np.argsort(-s)[:k]
        top_stems = set().union(*(self.stems[i] for i in order[:3])) if len(order) else set()
        missing = sorted(self.key_terms(query) - top_stems)
        out = []
        for i in order:
            cov = len(q_stems & self.stems[i]) / len(q_stems) if q_stems else 0.0
            out.append(Passage(self.chunks[i], float(s[i]), cov, missing))
        return out


# ======================================================================= answer
@dataclass
class Answer:
    question: str
    text: str
    supported: bool
    mode: str                                   # documents | data | data+documents | idk
    citations: list = field(default_factory=list)
    retrieval: list = field(default_factory=list)


def _sentences(text: str) -> list[str]:
    parts = re.split(r"(?<=[.;:])\s+(?=[A-Z(•])|\s+(?=\(\d+\)\s)|\s•\s", text)
    return [p.strip(" •") for p in parts if len(p.split()) >= 4]


def _doc_citation(n: int, p: Passage) -> dict:
    c = p.chunk
    return {"n": n, "type": "document", "doc_id": c["doc_id"], "title": c["short"], "page": c["page"],
            "section": c["section"], "url": c["url"], "chunk_id": c["chunk_id"], "publisher": c["publisher"],
            "score": round(p.score, 3)}


class HeatShieldAssistant:
    def __init__(self, index: DocumentIndex | None = None, gold_dir=None, thresholds: dict | None = None):
        self.index = index or DocumentIndex.load()
        self.gold_dir = gold_dir or config.GOLD
        self.th = thresholds or load_thresholds()

    # ---------------------------------------------------------------- routing
    def ask(self, question: str) -> Answer:
        q = question.strip()
        cities = sorted({v for k, v in CITY_ALIASES.items() if re.search(rf"\b{k}\b", q.lower())})
        wants_data = bool(DATA_WORDS.search(q)) and (bool(cities) or re.search(r"\b(which|all|each) cit", q, re.I))
        if wants_data:
            return self._data_answer(q, cities or list(config.CITIES))
        return self.answer_from_documents(q)

    # ------------------------------------------------------------- documents
    def retrieve(self, q: str, k: int = 5) -> tuple[list[Passage], bool]:
        hits = self.index.search(q, k)
        top = hits[0] if hits else None
        return hits, decide(top, self.th) if top and _tokens(q) else False

    def answer_from_documents(self, q: str, start_n: int = 1) -> Answer:
        hits, ok = self.retrieve(q)
        retrieval = [{"chunk_id": h.chunk["chunk_id"], "score": round(h.score, 3), "coverage": round(h.coverage, 2),
                      "missing_key_terms": h.missing_key_terms} for h in hits]
        if not ok:
            return Answer(q, IDK, False, "idk", retrieval=retrieval)
        # Keep passages that are close to the best one.
        keep = [h for h in hits if h.score >= max(self.th["floor_score"], 0.55 * hits[0].score)][:4]
        text, cits = self._extractive(q, keep, start_n)
        return Answer(q, text, True, "documents", cits, retrieval)

    def _extractive(self, q: str, passages: list[Passage], start_n: int = 1, max_points: int = 4):
        qv = self.index.word.transform([expand(q)])
        q_stems = {_stem(t) for t in _tokens(q)}
        cands = []
        for pi, p in enumerate(passages):
            for s in _sentences(p.chunk["text"]):
                sim = float((self.index.word.transform([s]) @ qv.T).toarray()[0, 0])
                overlap = len(q_stems & {_stem(t) for t in _tokens(s)}) / max(1, len(q_stems))
                cands.append((sim + 0.3 * overlap - 0.02 * pi, pi, s))
        cands.sort(key=lambda x: -x[0])
        chosen, seen = [], set()
        for score, pi, s in cands:
            key = s[:60].lower()
            if key in seen or score <= 0.02:
                continue
            seen.add(key)
            chosen.append((pi, s))
            if len(chosen) >= max_points:
                break
        used = sorted({pi for pi, _ in chosen})
        num = {pi: start_n + i for i, pi in enumerate(used)}
        lines = [f"- {s.rstrip('.;:')}. [{num[pi]}]" for pi, s in chosen]
        cits = [_doc_citation(num[pi], passages[pi]) for pi in used]
        return "According to the official guidance:\n" + "\n".join(lines), cits

    # ---------------------------------------------------------------- data
    def _gold(self):
        """Gold tables, re-read whenever the pipeline has promoted a new version."""
        names = ("heat_daily.csv", "predictions.csv", "forecast_daily.csv")
        stamp = tuple((self.gold_dir / n).stat().st_mtime if (self.gold_dir / n).exists() else 0 for n in names)
        if getattr(self, "_gold_stamp", None) != stamp:
            def read(name, dates):
                path = self.gold_dir / name
                return pd.read_csv(path, parse_dates=dates) if path.exists() else pd.DataFrame()
            self._gold_cache = (read(names[0], ["date"]), read(names[1], ["issue_date", "target_date"]),
                                read(names[2], ["date"]))
            self._gold_stamp = stamp
        return self._gold_cache

    def _data_answer(self, q: str, cities: list[str]) -> Answer:
        daily, preds, nwp = self._gold()
        m = re.search(r"(\d{4}-\d{2}-\d{2})", q)
        today = pd.Timestamp.now(tz=config.LOCAL_TZ).normalize().tz_localize(None)
        lines, cits, worst = [], [], None
        if m:                                          # a specific past date
            day = pd.Timestamp(m.group(1))
            for city in cities:
                row = daily[(daily["city"] == city) & (daily["date"] == day)]
                n = len(cits) + 1
                if row.empty or pd.isna(row.iloc[0]["hi_max_c"]):
                    lines.append(f"- {config.CITIES[city]['name']}: no complete Gold record for {day.date()}.")
                    continue
                r = row.iloc[0]
                lines.append(f"- {config.CITIES[city]['name']} on {day.date()}: maximum heat index **{r['hi_max_c']:.1f} °C** "
                             f"({r['risk_level']}), max temperature {r['tmax_c']:.1f} °C, mean humidity {r['rh_mean_pct']:.0f} %. [{n}]")
                cits.append({"n": n, "type": "gold_row", "table": "gold/heat_daily.csv", "row_id": r["row_id"]})
                worst = r["risk_level"]
        else:
            if re.search(r"\byesterday\b", q, re.I):
                target = today - timedelta(days=1)
            elif re.search(r"\b(tomorrow)\b", q, re.I):
                target = today + timedelta(days=1)
            elif re.search(r"\bday after\b", q, re.I):
                target = today + timedelta(days=2)
            else:
                target = today
            for city in cities:
                name = config.CITIES[city]["name"]
                p = preds[(preds["city"] == city) & (preds["target_date"] == target)] if len(preds) else preds
                f = nwp[(nwp["city"] == city) & (nwp["date"] == target)] if len(nwp) else nwp
                obs = daily[(daily["city"] == city) & (daily["date"] == target)]
                if len(p):
                    r = p.iloc[0]
                    n = len(cits) + 1
                    lines.append(f"- {name}, {target.date()}: HeatShield model forecasts a maximum heat index of "
                                 f"**{r['pred']:.1f} °C** (90 % interval {r['lo90']:.1f}–{r['hi90']:.1f} °C) → "
                                 f"**{r['predicted_risk_level']}**. [{n}]")
                    cits.append({"n": n, "type": "gold_row", "table": "gold/predictions.csv", "row_id": r["row_id"]})
                    worst = max([worst, r["predicted_risk_level"]], key=_rank) if worst else r["predicted_risk_level"]
                if len(f) and pd.notna(f.iloc[0]["hi_max_c"]):
                    r = f.iloc[0]
                    n = len(cits) + 1
                    lines.append(f"  - Open-Meteo NWP forecast for the same day: {r['hi_max_c']:.1f} °C ({r['risk_level']}). [{n}]")
                    cits.append({"n": n, "type": "gold_row", "table": "gold/forecast_daily.csv", "row_id": r["row_id"]})
                    worst = max([worst, r["risk_level"]], key=_rank) if worst else r["risk_level"]
                elif not len(p) and len(obs) and pd.notna(obs.iloc[0]["hi_max_c"]):
                    r = obs.iloc[0]
                    n = len(cits) + 1
                    lines.append(f"- {name}, {target.date()} (observed): maximum heat index {r['hi_max_c']:.1f} °C ({r['risk_level']}). [{n}]")
                    cits.append({"n": n, "type": "gold_row", "table": "gold/heat_daily.csv", "row_id": r["row_id"]})
                    worst = r["risk_level"]
                if not any(name in ln for ln in lines):
                    lines.append(f"- {name}: no forecast or observation is available for {target.date()} in the trusted Gold data.")
        if not cits:
            return Answer(q, "I don't know — the trusted Gold data has no record that answers this.\n" + "\n".join(lines),
                          False, "idk")
        text = "**From HeatShield data:**\n" + "\n".join(lines)
        mode = "data"
        if worst and _rank(worst) >= _rank("Extreme Caution") or GUIDANCE_WORDS.search(q):
            gq = GUIDANCE_QUERIES.get(worst or "Caution", GUIDANCE_QUERIES["Caution"])
            g = self.answer_from_documents(gq, start_n=len(cits) + 1)
            if g.supported:
                text += f"\n\n**Official guidance for {worst or 'hot'} conditions:**\n" + g.text.split("\n", 1)[1]
                cits += g.citations
                mode = "data+documents"
        return Answer(q, text, True, mode, cits)


GUIDANCE_QUERIES = {
    "Caution": "stay hydrated drink plenty of water avoid direct sunlight peak hours",
    "Extreme Caution": "individual preventive measures hydrated avoid sunlight peak hours 11:00 AM to 4:00 PM loose clothing",
    "Danger": "heatstroke symptoms dizziness nausea consult doctor avoid outdoor work peak hours hydrated elderly children",
    "Extreme Danger": "heatstroke emergency seek immediate medical attention cooling shelters avoid outdoor activities",
}


def _rank(level) -> int:
    names = [n for n, _, _ in config.RISK_LEVELS]
    return names.index(level) if level in names else -1


def decide(top: Passage, th: dict) -> bool:
    """Answer only if every specific query term occurs in the retrieved passages,
    or at most ``max_missing_key_terms`` are absent *and* retrieval is strong."""
    if top.score < th["floor_score"]:
        return False
    if any(t.isdigit() for t in top.missing_key_terms):     # asks about a year no document covers
        return False
    missing = len(top.missing_key_terms)
    return missing == 0 or (missing <= th["max_missing_key_terms"] and top.score >= th["min_score"])


def load_thresholds() -> dict:
    try:
        return {**DEFAULT_THRESHOLDS, **json.loads(THRESHOLDS_FILE.read_text(encoding="utf-8"))}
    except (OSError, ValueError):
        return dict(DEFAULT_THRESHOLDS)


def format_citations(ans: Answer) -> str:
    out = []
    for c in ans.citations:
        if c["type"] == "document":
            sec = f", {c['section']}" if c["section"] else ""
            out.append(f"[{c['n']}] {c['title']} — page {c['page']}{sec}. {c['publisher']}. {c['url']}")
        else:
            out.append(f"[{c['n']}] Gold row `{c['row_id']}` ({c['table']})")
    return "\n".join(out)
