import re
from typing import Any, Dict, List, Optional
import fitz

class SectionNode:
    def __init__(self, title: str, level: int = 1):
        self.title = title
        self.level = level
        self.text_content: list[str] = []
        self.subsections: list['SectionNode'] = []
        self.page: int = 1

    def to_dict(self) -> Dict[str, Any]:
        return {
            "title": self.title,
            "text": "\\n".join(self.text_content).strip(),
            "page": self.page,
            "subsections": [sub.to_dict() for sub in self.subsections]
        }

def is_major_section_title(text: str, font_size: float, base_font_size: float) -> bool:
    """
    Heuristic to determine if a block of text is a major section title (Level 1).
    Uses font size > base_font_size + 2, or SEC standard items (e.g. ITEM 1A).
    """
    text = text.strip()
    if not text:
        return False
    
    # SEC Item pattern
    if re.match(r"^(PART|ITEM)\s+[IVX0-9]+[A-Z]?\.?\s*([A-Za-z].{2,})?$", text, re.IGNORECASE):
        return True
        
    # Standard known titles often in all caps or title case
    if text.isupper() and len(text) > 4 and len(text) < 100:
        return True
        
    # Font size significantly larger than body text
    if font_size >= base_font_size + 2.0 and len(text) < 150:
        return True
        
    return False

def is_subsection_title(text: str, font_size: float, base_font_size: float) -> bool:
    """
    Heuristic to determine if a block of text is a subsection title (Level 2).
    """
    text = text.strip()
    if not text:
        return False
        
    # Slightly larger font size
    if font_size >= base_font_size + 0.5 and font_size < base_font_size + 2.0 and len(text) < 150:
        return True
        
    # Capitalized words (Title Case)
    if text.istitle() and len(text) < 100:
        return True
        
    return False

def extract_document_structure(doc: fitz.Document, doc_name: str) -> Dict[str, Any]:
    """
    Iterate through the PDF blocks to build a hierarchical tree of sections.
    """
    root_node = SectionNode("Document Root", level=0)
    current_major = SectionNode("Preamble", level=1)
    current_minor = None
    
    root_node.subsections.append(current_major)
    
    # Estimate base font size (simplistic approach: most common font size)
    font_sizes = []
    for page in doc:
        blocks = page.get_text("dict").get("blocks", [])
        for b in blocks:
            if "lines" in b:
                for l in b["lines"]:
                    for s in l["spans"]:
                        if s["text"].strip():
                            font_sizes.append(s["size"])
    
    if font_sizes:
        # Get mode or median font size as base body text size
        base_font_size = max(set(font_sizes), key=font_sizes.count)
    else:
        base_font_size = 11.0 # fallback
        
    for page_num, page in enumerate(doc, start=1):
        blocks = page.get_text("dict").get("blocks", [])
        for b in blocks:
            if "lines" not in b:
                continue
                
            block_text = ""
            max_font_size = 0.0
            
            for l in b["lines"]:
                for s in l["spans"]:
                    text = s["text"].strip()
                    if text:
                        block_text += text + " "
                        max_font_size = max(max_font_size, s["size"])
            
            block_text = block_text.strip()
            if not block_text:
                continue
                
            # Determine if this block is a heading
            if is_major_section_title(block_text, max_font_size, base_font_size):
                current_major = SectionNode(block_text, level=1)
                current_major.page = page_num
                current_minor = None
                root_node.subsections.append(current_major)
            elif is_subsection_title(block_text, max_font_size, base_font_size):
                current_minor = SectionNode(block_text, level=2)
                current_minor.page = page_num
                current_major.subsections.append(current_minor)
            else:
                # Add content to the current lowest active node
                if current_minor:
                    current_minor.text_content.append(block_text)
                else:
                    current_major.text_content.append(block_text)
                    
    # Format output
    return {
        "document": doc_name,
        "sections": [sub.to_dict() for sub in root_node.subsections]
    }
