"""Turn the official PDFs in Bronze into citable text chunks (data/rag/).

Each chunk keeps its document id, publisher, title, source URL, PDF page and
the section heading it sits under, so every answer can cite "document, page,
section". The PDF hash is checked against the manifest first: a document whose
bytes changed since Member 1 recorded it is refused.

Pages that carry no extractable text (image posters, blank annexes) and the
Urdu page, whose PDF text layer is garbled, are skipped and listed in
``documents.json`` so the gap is visible.

Usage: ``python -m heatshield.rag.ingest`` (part of ``make -C src rag``)
"""
from __future__ import annotations

import json
import logging
import re
import sys

from pypdf import PdfReader

from heatshield import bronze, config

OUT_DIR = config.DATA / "rag"          # own folder: pipeline promotion swaps data/silver
CHUNKS = OUT_DIR / "chunks.jsonl"
DOC_INDEX = OUT_DIR / "documents.json"
TARGET_WORDS, MAX_WORDS = 110, 170

DOC_META = {
    "ndma_heatwave_advisory_apr2025": {
        "title": "NDMA Heatwave Advisory: Heatwave Conditions Predicted 26–30 April 2025",
        "short": "NDMA Heatwave Advisory (25 Apr 2025)", "date": "2025-04-25",
    },
    "pdma_sindh_heatwave_alert_may2025": {
        "title": "PDMA Sindh Heatwave Alert, 15 May 2025 (incl. PMD Heatwave-Alert and Karachi 3-day forecast)",
        "short": "PDMA Sindh / PMD Heatwave Alert (15 May 2025)", "date": "2025-05-15", "headings": False,
    },
    "pdma_sindh_heatwave_sops": {
        "title": "SOPs Heatwave Management, Sindh",
        "short": "PDMA Sindh Heatwave SOPs", "date": "2025",
    },
}

_BOILERPLATE = [
    r"^SOPs Heatwave Management, Sindh\s*$", r"^Provincial Disaster Management Authority \(PDMA\) Sindh\s*$",
    r"^_{5,}\s*$", r"^Page \| \d+\s*$", r"^Page \d+ of \d+\s*$", r"^\s*\d{1,4}(\.\d+)?\s*$",
    r"^(April May June July|Every 5 Years|Mean Temperature °C|Temperature in °C)\s*$",
    r"^\s*(1990 1995 2000 2005 2010 2015 2020 2025)\s*$", r"^\s*g\s*$",
    r"^(MOST IMMEDIATE|MOST URGENT/BY FAX/WHATSAPP)\s*$", r"^Heat Index, (Upper|Central|Lower) Sindh\s*$",
    r"^Source: Pakistan Met Department\s*$",
]
_BOILER_RE = [re.compile(p) for p in _BOILERPLATE]
_HEADING_RE = re.compile(r"^(?=.*[A-Z]{3})[A-Z0-9 &/()',.\-–]{6,}$")
_SUBHEAD_RE = re.compile(r"^(?:[a-d]\.\s*)?(Mitigation\s*/\s*Preparedness|Response|Recovery & Rehabilitation|"
                         r"Institutional Measures|Individual Preventive Measures|Vehicle Safety and Travel Precautions|"
                         r"Additional Recommendations|Health|Heat Index in \w+ Sindh|Possible Impacts and advice:?)\s*$", re.I)
_BULLET_RE = re.compile(r"^\s*(•|||-|\(\d+\)|\d+\.|[a-d]\.)\s+")


def clean_text(text: str) -> str:
    text = text.replace("", "•").replace("’", "'").replace(" ", " ")
    text = re.sub(r"(\w) -(\w)", r"\1-\2", text)          # "heat -related" -> "heat-related"
    text = re.sub(r"[ \t]+", " ", text)
    return text


def _is_urdu(text: str) -> bool:
    letters = [c for c in text if c.isalpha()]
    return bool(letters) and sum(ord(c) > 0x0600 for c in letters) / len(letters) > 0.3


def page_units(text: str, headings: bool = True) -> list[tuple[str, str]]:
    """Split a page into (kind, text) units: headings, subheadings and paragraphs/bullets."""
    lines = [ln.strip() for ln in clean_text(text).splitlines()]
    lines = [ln for ln in lines if ln and not any(r.match(ln) for r in _BOILER_RE)]
    units, buf = [], []
    def flush():
        if buf:
            units.append(("para", " ".join(buf)))
            buf.clear()
    for ln in lines:
        if _SUBHEAD_RE.match(ln):
            flush(); units.append(("subhead", _SUBHEAD_RE.match(ln).group(1).rstrip(":")))
        elif headings and _HEADING_RE.match(ln) and len(ln.split()) <= 12 and "," not in ln                 and not re.search(r"DIRECTOR|SECRETARY|PHONE|FAX|PLOT|^ED |^ID:|^APS ", ln):
            flush(); units.append(("heading", ln.title() if ln.isupper() else ln))
        elif _BULLET_RE.match(ln) or (buf and buf[-1].endswith((".", ":", ";")) and ln[:1].isupper()):
            flush(); buf.append(_BULLET_RE.sub("", ln) if ln.startswith(("•",)) else ln)
        else:
            buf.append(ln)
    flush()
    return units


def chunk_document(doc_id: str, pages: list[str], meta: dict) -> tuple[list[dict], list[dict]]:
    chunks, skipped = [], []
    heading = subhead = ""
    for page_no, raw in enumerate(pages, start=1):
        if _is_urdu(raw):
            skipped.append({"page": page_no, "reason": "Urdu text layer is not reliably extractable"})
            continue
        if raw.count("....") > 5:
            skipped.append({"page": page_no, "reason": "table of contents (would compete with the real sections)"})
            continue
        units = page_units(raw, meta.get("headings", True))
        words = sum(len(t.split()) for k, t in units if k == "para")
        if words < 15:
            skipped.append({"page": page_no, "reason": "no extractable body text (image, chart or blank page)"})
            continue
        cur, cur_words, n = [], 0, 0
        def emit():
            nonlocal cur, cur_words, n
            if cur and cur_words >= 8:
                n += 1
                section = " › ".join(s for s in (heading, subhead) if s)
                chunks.append({
                    "chunk_id": f"{doc_id}#p{page_no}-c{n}", "doc_id": doc_id, "page": page_no,
                    "section": section, "text": " ".join(cur),
                    "search_text": f"{section}. {' '.join(cur)}", **meta})
                cur, cur_words = [], 0
        for kind, text in units:
            if kind == "heading":
                emit(); heading, subhead = text, ""
            elif kind == "subhead":
                emit(); subhead = text
            else:
                w = len(text.split())
                if cur and cur_words + w > MAX_WORDS:
                    emit()
                cur.append(text); cur_words += w
                if cur_words >= TARGET_WORDS:
                    emit()
        emit()
    return chunks, skipped


def ingest() -> dict:
    logging.getLogger("pypdf").setLevel(logging.ERROR)
    manifest = bronze.load_manifest()
    all_chunks, docs = [], []
    for pdf in sorted(config.BRONZE_DOCS.glob("*.pdf")):
        doc_id = pdf.stem
        rel = pdf.relative_to(config.ROOT).as_posix()
        entry = manifest.get(rel, {})
        sha = bronze.sha256_of(pdf)
        record = {"doc_id": doc_id, "file": rel, "publisher": entry.get("publisher", "unknown"),
                  "url": entry.get("page_url", ""), "sha256": sha, "hash_verified": sha == entry.get("sha256")}
        if not record["hash_verified"]:
            record["status"] = "refused: not in manifest or SHA-256 mismatch"
            docs.append(record)
            continue
        meta = {"publisher": record["publisher"], "url": record["url"],
                **DOC_META.get(doc_id, {"title": doc_id, "short": doc_id, "date": ""})}
        pages = [p.extract_text() or "" for p in PdfReader(str(pdf)).pages]
        chunks, skipped = chunk_document(doc_id, pages, meta)
        record.update({"status": "ingested", "title": meta["title"], "pages": len(pages),
                       "chunks": len(chunks), "skipped_pages": skipped})
        docs.append(record)
        all_chunks += chunks
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    with CHUNKS.open("w", encoding="utf-8") as fh:
        for c in all_chunks:
            fh.write(json.dumps(c, ensure_ascii=False) + "\n")
    DOC_INDEX.write_text(json.dumps(docs, indent=2, ensure_ascii=False), encoding="utf-8")
    return {"documents": docs, "chunks": len(all_chunks)}


def ensure_documents(timeout: int = 60) -> list[str]:
    """Download any manifest-listed document that is missing locally from its
    official URL and keep it only if its SHA-256 matches the manifest.

    The NDMA / PDMA / PMD PDFs are not openly licensed (see docs/sources.md),
    so public deployments do not ship them; they fetch them from the publisher.
    """
    import requests
    problems = []
    for rel, entry in bronze.load_manifest().items():
        if entry.get("source") != "Official heatwave document":
            continue
        path = config.ROOT / rel
        if path.exists():
            continue
        try:
            r = requests.get(entry["page_url"], timeout=timeout,
                             headers={"User-Agent": "HeatShield-Pakistan (student project)"})
            r.raise_for_status()
            if bronze.hashlib.sha256(r.content).hexdigest() != entry["sha256"]:
                problems.append(f"{rel}: publisher file changed (hash mismatch) - not used")
                continue
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(r.content)
        except Exception as exc:  # noqa: BLE001
            problems.append(f"{rel}: {type(exc).__name__}")
    return problems


def ensure_index() -> None:
    """Build the chunk index if it is missing or older than any source PDF."""
    ensure_documents()
    pdfs = list(config.BRONZE_DOCS.glob("*.pdf"))
    if not CHUNKS.exists() or any(p.stat().st_mtime > CHUNKS.stat().st_mtime for p in pdfs):
        ingest()


def main() -> int:
    for problem in ensure_documents():       # fetch any official PDF that is not shipped
        print("document not available:", problem)
    res = ingest()
    for d in res["documents"]:
        print(f"{d['doc_id']}: {d['status']} - {d.get('chunks', 0)} chunks, "
              f"skipped pages {[s['page'] for s in d.get('skipped_pages', [])]}")
    print("total chunks:", res["chunks"], "->", CHUNKS.relative_to(config.ROOT))
    return 0 if all(d["hash_verified"] for d in res["documents"]) else 1


if __name__ == "__main__":
    sys.exit(main())
