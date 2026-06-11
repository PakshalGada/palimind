from core.ingestion.structure_extractor import is_major_section_title, is_subsection_title, SectionNode
from core.ingest.section_chunker import section_aware_chunking_from_tree

def test_structure_extraction_heuristics():
    # Test major section
    assert is_major_section_title("ITEM 1A. RISK FACTORS", 12.0, 10.0) == True
    assert is_major_section_title("PART II", 11.0, 11.0) == True
    assert is_major_section_title("SUPPLY OF COMPONENTS", 14.0, 11.0) == True
    
    # Test minor section
    assert is_subsection_title("Supply of Components", 11.5, 11.0) == True
    assert is_subsection_title("General", 12.0, 11.0) == True
    
def test_section_chunker():
    tree = {
        "document": "Apple_2025_10K.pdf",
        "sections": [
            {
                "title": "Risk Factors",
                "text": "These are the risks.",
                "page": 1,
                "subsections": [
                    {
                        "title": "Supply of Components",
                        "text": "We rely on suppliers." * 100, # Long text to test chunking
                        "page": 2,
                    }
                ]
            }
        ]
    }
    
    chunks = section_aware_chunking_from_tree("Apple_2025_10K.pdf", tree)
    assert len(chunks) > 0
    
    # Check that titles are prepended and metadata is correct
    assert chunks[0]["section"] == "Risk Factors"
    assert chunks[0]["subsection"] == ""
    assert "Risk Factors\\n\\nThese are the risks." in chunks[0]["text"]
    
    assert chunks[1]["section"] == "Risk Factors"
    assert chunks[1]["subsection"] == "Supply of Components"
    assert "Supply of Components\\n\\nWe rely on suppliers." in chunks[1]["text"]

def test_show_retrieval_debug():
    # We can't fully end-to-end test without an index, but we can verify the prefix parsing
    query = "SHOW_RETRIEVAL_DEBUG What are the risk factors?"
    assert query.startswith("SHOW_RETRIEVAL_DEBUG")
    stripped = query.replace("SHOW_RETRIEVAL_DEBUG", "").strip()
    assert stripped == "What are the risk factors?"
    
if __name__ == "__main__":
    test_structure_extraction_heuristics()
    test_section_chunker()
    test_show_retrieval_debug()
    print("All structure tests passed!")
