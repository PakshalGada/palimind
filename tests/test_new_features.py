# pyrefly: ignore [missing-import]
import pytest
from pathlib import Path
from core.retrieval.query_rewriter import rewrite_query
from core.analysis.document_diff import compute_diff

def test_query_rewriter():
    query = "What exact sentence was added to Apple's Supply of Components risk section in 2025 that was not present in 2023?"
    # We will just test that it doesn't crash and returns default if ollama is not up, or returns proper object.
    res = rewrite_query(query, "http://localhost:11434", "gemma:latest")
    assert res is not None
    assert res.original == query

def test_document_diff():
    text2023 = "Apple relies on suppliers. The supply chain is complex."
    text2025 = "Apple relies on suppliers. The supply chain is complex. Restrictions on international trade can increase the cost."
    
    # Run compute_diff
    diff = compute_diff(text2023, text2025, "http://localhost:11434", "nomic-embed-text")
    
    assert "Restrictions on international trade can increase the cost." in diff["added"]
    assert not diff["removed"]
    assert not diff["modified"]

def test_document_diff_modified():
    text2023 = "The company expects revenue to grow by 10% next year."
    text2025 = "The company expects revenue to grow by 15% next year."
    
    diff = compute_diff(text2023, text2025, "http://localhost:11434", "nomic-embed-text")
    
    assert diff["modified"]
    assert "From: The company expects revenue to grow by 10% next year. -> To: The company expects revenue to grow by 15% next year." in diff["modified"]
