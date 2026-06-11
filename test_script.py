from core.analysis.document_diff import compute_diff

text2023 = "Apple relies on suppliers. The supply chain is complex."
text2025 = "Apple relies on suppliers. The supply chain is complex. Restrictions on international trade can increase the cost."

diff = compute_diff(text2023, text2025, "http://localhost:11434", "nomic-embed-text")

print("Added:", diff["added"])
assert "Restrictions on international trade can increase the cost." in diff["added"]

text2023_mod = "The company expects revenue to grow by 10% next year."
text2025_mod = "The company expects revenue to grow by 15% next year."

diff_mod = compute_diff(text2023_mod, text2025_mod, "http://localhost:11434", "nomic-embed-text")
print("Modified:", diff_mod["modified"])

print("Tests passed!")
