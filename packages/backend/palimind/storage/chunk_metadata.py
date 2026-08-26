from dataclasses import dataclass
from typing import Any


@dataclass
class ChunkMetadata:
    chunk_id: str
    document_name: str
    year: int | None
    section: str
    page: int | None
    chunk_index: int
    text: str

    @classmethod
    def from_db_row(cls, row: dict[str, Any]) -> "ChunkMetadata":
        return cls(
            chunk_id=str(row.get("chunk_db_id", "")),
            document_name=row.get("file_path", ""),
            year=row.get("doc_year"),
            section=row.get("section_title", ""),
            page=row.get("page_number"),
            chunk_index=row.get("chunk_index", 0),
            text=row.get("content", ""),
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "chunk_id": self.chunk_id,
            "document_name": self.document_name,
            "year": self.year,
            "section": self.section,
            "page": self.page,
            "chunk_index": self.chunk_index,
            "text": self.text,
        }
