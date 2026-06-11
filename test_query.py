import sys
from pathlib import Path
from core.querying import query

if __name__ == "__main__":
    root = Path(".")
    q = "What exact sentence was added to Apple's Supply of Components risk section in 2025 that was not present in 2023?"
    print(f"Query: {q}")
    
    try:
        res = query(root, q)
        print("Answer:", res.answer)
        print("Context Sources:", res.context.sources)
        print("Context Texts:", res.context.text_contexts)
    except Exception as e:
        print("Error:", e)
