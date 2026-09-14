"""Tests for knowledge-doc optimizations (09-14, four items).

① ⑥ encoding fallback: UTF-8 fails → try GB18030 before rejecting.
② ③ chunk anchoring: each chunk carries a「来源文件名 · 第N段」header so
   retrieval surfaces the source, and adjacent chunks overlap by ~12%.
① retrieval budget: knowledge_docs get a larger per-collection quota
   (KNOWLEDGE_K_PER_COLLECTION=8 vs 5) — lore files are the main carrier of
   long-form setting detail.
③ source annotation: _format_retrieval_context renders knowledge hits as
   [知识文档/文件名·N] instead of dropping them.
"""
import pytest

from app.services.knowledge_doc import chunk_text, decode_upload
from app.pipeline.nodes import _format_retrieval_context


def test_decode_utf8_passthrough() -> None:
    assert decode_upload("正常文本".encode("utf-8")) == "正常文本"


def test_decode_gbk_fallback() -> None:
    """Windows 记事本 ANSI (GB18030) files decode instead of being rejected."""
    raw = "力量体系：练气、筑基、金丹。".encode("gb18030")
    assert decode_upload(raw) == "力量体系：练气、筑基、金丹。"


def test_decode_binary_still_rejected() -> None:
    """Truly binary bytes (invalid in both UTF-8 and GB18030) still raise."""
    with pytest.raises(Exception):
        decode_upload(bytes([0x81, 0x40, 0xFF, 0xFE, 0x81]))


def test_chunks_carry_source_anchor_and_overlap() -> None:
    """Chunks are prefixed with「来源·第N段」and consecutive chunks share
    the previous tail (~12% overlap) so cross-boundary sentences survive."""
    paras = [f"第{i}段设定。" + "细节内容" * 40 for i in range(6)]
    text = "\n\n".join(paras)
    chunks = chunk_text(text, chunk_size=400, source="力量体系.txt")
    assert len(chunks) > 1
    assert chunks[0].startswith("【来源·力量体系.txt·第1段】")
    assert "【来源·力量体系.txt·第2段】" in chunks[1]
    # overlap: tail of chunk 0 (minus its anchor) appears in chunk 1
    tail = chunks[0].split("】", 1)[1][-40:]
    assert tail in chunks[1]


def test_chunk_no_source_no_anchor() -> None:
    """source=None keeps the plain behavior (no anchor, unit-test friendly)."""
    chunks = chunk_text("段落一。\n\n段落二。", chunk_size=400)
    assert chunks == ["段落一。\n\n段落二。"]


def test_retrieval_context_annotates_knowledge_hits() -> None:
    class Hit:
        def __init__(self):
            self.payload = {"title": "力量体系.txt", "chunk_index": 2, "content": "金丹期可御空飞行。"}
            self.entity_type = "knowledge_doc"
            self.score = 0.91

    ctx = _format_retrieval_context([Hit()])
    assert "[知识文档/力量体系.txt·3]" in ctx
    assert "金丹期可御空飞行" in ctx


def test_knowledge_k_constant_exposed() -> None:
    """① larger knowledge quota is a module constant others can tune."""
    from app.services.retrieval import KNOWLEDGE_K_PER_COLLECTION, DEFAULT_K_PER_COLLECTION

    assert KNOWLEDGE_K_PER_COLLECTION > DEFAULT_K_PER_COLLECTION
