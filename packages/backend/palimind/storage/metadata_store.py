import re
from typing import TypedDict


class MetadataFilter(TypedDict):
    years: list[int]
    sections: list[str]
    document_names: list[str]
    is_comparison: bool


# Known standard section headers in financial or general docs
# Organized by 10-K Item for easy lookup and name resolution
SECTION_ALIASES: dict[str, list[str]] = {
    # Item 1: Business
    "Business": ["item 1", "business", "overview", "company overview"],
    "Human Capital": [
        "human capital",
        "human capital resources",
        "employees",
        "people",
        "workforce",
        "talent",
    ],
    "Competition": ["competition", "competitive landscape", "competitive environment"],
    "Supply of Components": [
        "supply of components",
        "components",
        "suppliers",
        "supply chain",
        "manufacturing",
        "sourcing",
    ],
    "Products": [
        "products",
        "product",
        "wearables",
        "home",
        "accessories",
        "iphone",
        "ipad",
        "mac",
        "services",
    ],
    "Customers": ["customers", "customer", "distribution", "channel", "retail"],
    "Intellectual Property": ["intellectual property", "patents", "trademarks", "copyrights", "ip"],
    "Government Regulations": ["government regulations", "regulatory", "regulation", "compliance"],
    "Available Information": ["available information", "sec filings", "investor", "website"],
    # Item 1A: Risk Factors
    "Risk Factors": ["risk factors", "risk", "item 1a", "uncertainties", "threats"],
    "Market Risk": ["market risk", "interest rate risk", "currency risk", "foreign exchange"],
    # Item 2: Properties
    "Properties": ["properties", "facilities", "real estate", "offices", "stores"],
    # Item 3: Legal Proceedings
    "Legal Proceedings": ["legal proceedings", "litigation", "legal matters", "lawsuits"],
    # Item 5: Market for Registrant's Common Equity
    "Market Information": ["market information", "stock", "equity", "shareholders", "dividends"],
    # Item 6: Selected Financial Data
    "Selected Financial Data": ["selected financial data", "financial data", "summary financial"],
    # Item 7: Management's Discussion & Analysis
    "Management's Discussion": [
        "management's discussion",
        "md&a",
        "results of operations",
        "financial condition",
    ],
    "Liquidity and Capital Resources": ["liquidity", "capital resources", "cash flow", "cash"],
    "Critical Accounting Estimates": [
        "critical accounting",
        "accounting estimates",
        "accounting policies",
    ],
    # Item 7A: Quantitative and Qualitative Disclosures About Market Risk
    "Market Risk Disclosures": ["quantitative", "qualitative", "market risk disclosures"],
    # Item 8: Financial Statements
    "Financial Statements": [
        "financial statements",
        "income statement",
        "balance sheet",
        "cash flow statement",
    ],
    "Revenue": ["revenue", "net sales", "sales by segment", "product revenue", "service revenue"],
    "Cost of Sales": ["cost of sales", "cost of goods sold", "cogs", "gross margin"],
    "Operating Expenses": [
        "operating expenses",
        "r&d",
        "research and development",
        "sg&a",
        "selling general and administrative",
    ],
    "Income Taxes": ["income taxes", "tax", "taxation", "tax provision"],
    # Item 9: Changes in and Disagreements with Accountants
    "Accountants": ["accountants", "accounting changes", "audit"],
    # Item 9A: Controls and Procedures
    "Controls and Procedures": [
        "controls",
        "procedures",
        "disclosure controls",
        "internal control",
    ],
    # Item 9B: Other Information
    "Other Information": ["other information", "subsequent events"],
}

KNOWN_SECTIONS = list(SECTION_ALIASES.keys())


def extract_metadata_from_query(query: str) -> MetadataFilter:
    """
    Extract metadata filters deterministically using Regex and keyword matching.
    < 2ms latency guaranteed (no LLMs).

    Returns canonical section names by checking query against all known
    section aliases, not just the canonical header name.
    """
    # Extract years (4 digit numbers between 1990 and 2050)
    years = []
    for match in re.finditer(r"\b(19[9][0-9]|20[0-4][0-9]|2050)\b", query):
        years.append(int(match.group(1)))

    years = sorted(list(set(years)))

    # Extract sections using alias-aware matching
    query_lower = query.lower()
    sections = []
    resolved_sections: set[str] = set()
    for canonical, aliases in SECTION_ALIASES.items():
        # Check if any alias appears in the query
        for alias in aliases:
            if alias in query_lower:
                resolved_sections.add(canonical)
                break
    # Also check exact canonical name match
    for sec in KNOWN_SECTIONS:
        if sec.lower() in query_lower:
            resolved_sections.add(sec)
    sections = sorted(resolved_sections)

    # Detect comparison
    comparison_keywords = {
        "compare",
        "difference",
        "change",
        "added",
        "removed",
        "new",
        "evolution",
        "timeline",
        "vs",
        "versus",
    }
    is_comparison = any(kw in query_lower for kw in comparison_keywords)

    return {
        "years": years,
        "sections": sections,
        "document_names": [],  # Could extract specific document names if needed
        "is_comparison": is_comparison,
    }
