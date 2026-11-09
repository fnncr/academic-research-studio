"""Deterministic first slice of editorial diagnostics 35 and 42.

This only identifies unusually similar *surface wording*, not semantic
equivalence, plagiarism, AI provenance or scientific accuracy.
"""
import hashlib
import re
from difflib import SequenceMatcher
from uuid import UUID

from app.editorial_registry_v2 import DIAGNOSTICS, EXTENSION_VERSION
from app.manuscript_schema import ManuscriptDocument

WORD = re.compile(r"[^\W_]+(?:[-’'][^\W_]+)*", re.UNICODE)
SENTENCE = re.compile(r"[^.!?\n]+(?:[.!?]+|$)", re.UNICODE)
VERSION = "lexical-near-duplicate-1.0.0"
MAX_FINDINGS = 40


def _tokens(text: str) -> list[str]:
    return [m.group().casefold().replace("ё", "е") for m in WORD.finditer(text)]


def _utf16_offset(text: str) -> int:
    return len(text.encode("utf-16-le")) // 2


def _text_nodes(document: ManuscriptDocument):
    """Only prose paragraphs; no quotations, citations, notes or bibliography."""
    for block in document.blocks:
        if block.type == "paragraph":
            yield str(block.id), block.text
        # Other block types need dedicated genre-aware rules, not a flattened DOCX.


def inspect(document: ManuscriptDocument, revision_id: UUID | str) -> dict:
    sentences = []
    for block_id, text in _text_nodes(document):
        for m in SENTENCE.finditer(text):
            sample = m.group().strip()
            words = _tokens(sample)
            # Short conventional expressions are not meaningful repetitions.
            if len(words) < 10:
                continue
            start = m.start() + len(m.group()) - len(m.group().lstrip())
            end = m.end()
            norm = " ".join(words)
            sentences.append((block_id, text, sample, words, norm, start, end))

    findings = []
    eligible_blocks = {item[0] for item in sentences}
    # Bounded by the document contract (<=250k chars); avoid quadratic scans
    # on thousands of sentences by comparing only a limited recent window and
    # exact normalized duplicates at arbitrary distances.
    recent = []
    exact = {}
    comparisons = 0
    for idx, entry in enumerate(sentences):
        block_id, text, sample, words, norm, start, end = entry
        peers = list(recent[-30:])
        if norm in exact and exact[norm] not in peers:
            peers.append(exact[norm])
        candidate = None
        for previous in peers:
            comparisons += 1
            old = sentences[previous]
            if old[0] == block_id:
                continue
            # Avoid false matches for genre-standard terminology alone.
            if norm != old[4]:
                overlap = len(set(words) & set(old[3])) / max(1, len(set(words) | set(old[3])))
                if overlap < .84 or SequenceMatcher(None, norm, old[4], autojunk=False).ratio() < .94:
                    continue
            candidate = previous
            break
        if candidate is not None and len(findings) < MAX_FINDINGS:
            old = sentences[candidate]
            # Nearby paragraphs -> 35; distant repeats -> 42.
            rule = "35" if idx - candidate <= 3 else "42"
            first = _utf16_offset(text[:start])
            last = _utf16_offset(text[:end])
            findings.append({
                "criterion_id": rule,
                "status": "candidate",
                "block_id": block_id,
                "start": first, "end": last,
                "quote": text[start:end],
                "quote_sha256": hashlib.sha256(text[start:end].encode("utf-8")).hexdigest(),
                "related_block_id": old[0],
                "explanation": "Похожая формулировка найдена в другом абзаце. Проверьте, действительно ли содержание дублируется; повтор может быть оправдан.",
                "rule_version": VERSION,
            })
        recent.append(idx)
        if norm not in exact:
            exact[norm] = idx
    coverage = [
        {"criterion_id": key, "title": value[0],
         "status": ("candidate" if any(f["criterion_id"] == key for f in findings)
                    else "no_issue" if value[1] == "lexical_candidate" and len(eligible_blocks) >= 2
                    else "insufficient_data"),
         "method": value[1]}
        for key, value in DIAGNOSTICS.items()
    ]
    return {
        "revision_id": str(revision_id),
        "registry_version": EXTENSION_VERSION,
        "rule_version": VERSION,
        "examined_prose_sentences": len(sentences),
        "comparisons": comparisons,
        "findings": findings,
        "coverage": coverage,
        "disclaimer": "Лексические кандидаты; не оценка происхождения ИИ, плагиата или процента Антиплагиата. Прямые цитаты и другие объекты не анализируются.",
    }
