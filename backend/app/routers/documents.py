"""
Document / Exhibit API
Serves exhibit PDFs and metadata from the project's source data directory.
Frontend expects:
  GET /api/documents/{project_id}/exhibits  → exhibit list with pdf_url
  GET /api/documents/{project_id}/pdf/{exhibit_id} → PDF file
"""
import json
import logging
from pathlib import Path

from fastapi import APIRouter, HTTPException
from fastapi.responses import FileResponse

from app.services import storage

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/documents", tags=["documents"])


def _get_source_path(project_id: str) -> Path:
    """Read source_path from project metadata.json, raise 404 on failure."""
    metadata_file = storage.get_project_dir(project_id) / "metadata.json"
    if not metadata_file.exists():
        raise HTTPException(status_code=404, detail="Project metadata not found")

    with open(metadata_file, "r", encoding="utf-8") as f:
        metadata = json.load(f)

    source_path = metadata.get("source_path", "")
    if not source_path:
        raise HTTPException(
            status_code=404, detail="No source_path in project metadata"
        )
    return Path(source_path)


def _exhibit_to_frontend(project_id: str, exhibit: dict) -> dict:
    """Convert metadata exhibit entry to the shape the frontend expects."""
    eid = exhibit.get("exhibit_id", "")
    category = eid[0].upper() if eid else "?"
    return {
        "id": eid,
        "name": eid,
        "category": category,
        "pdf_url": f"/api/documents/{project_id}/pdf/{eid}",
        "page_count": exhibit.get("page_count", 0),
    }


@router.get("/{project_id}/exhibits")
def list_exhibits(project_id: str):
    """List all exhibit documents for a project."""
    metadata_file = storage.get_project_dir(project_id) / "metadata.json"
    if not metadata_file.exists():
        raise HTTPException(status_code=404, detail="Project metadata not found")

    with open(metadata_file, "r", encoding="utf-8") as f:
        metadata = json.load(f)

    raw_exhibits = metadata.get("exhibits", [])
    exhibits = [_exhibit_to_frontend(project_id, e) for e in raw_exhibits]

    return {
        "project_id": project_id,
        "total": len(exhibits),
        "exhibits": exhibits,
    }


@router.get("/{project_id}/pdf/{exhibit_id}")
def get_exhibit_pdf(project_id: str, exhibit_id: str):
    """Serve exhibit PDF file from the project's source data directory."""
    source = _get_source_path(project_id)
    letter = exhibit_id[0].upper()

    # Try multiple naming conventions: A1.pdf, a1.pdf
    candidates = [
        source / "PDF" / letter / f"{exhibit_id}.pdf",
        source / "PDF" / letter / f"{exhibit_id.lower()}.pdf",
        source / "PDF" / letter / f"{exhibit_id.upper()}.pdf",
    ]

    for pdf_path in candidates:
        if pdf_path.exists():
            return FileResponse(
                path=str(pdf_path),
                media_type="application/pdf",
                filename=f"{exhibit_id}.pdf",
            )

    raise HTTPException(status_code=404, detail=f"PDF not found: {exhibit_id}")
