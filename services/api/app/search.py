"""
Search router: POST /search

Filters (all optional — omit to match all):
    video_ids:            list[UUID]  — restrict to specific videos
    person_ids:           list[UUID]  — frames containing these known persons
    classes:              list[str]   — YOLO class names (e.g. ["person","car"])
    include_unknown_faces: bool       — include frames with unmatched faces
    date_from:            str | None  — ISO 8601 datetime; filter by video.recorded_at
    date_to:              str | None  — ISO 8601 datetime
    min_confidence:       float       — minimum YOLO detection confidence (default 0.0)
    page:                 int         — 1-based page number (default 1)
    page_size:            int         — rows per page (default 20, max 100)

Response:
    results: list of FrameResult
    pagination: { page, page_size, total, has_next }
"""
import logging
from typing import Optional
from uuid import UUID

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, field_validator

from .db import get_pool

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/search", tags=["search"])


# ── Request / Response models ─────────────────────────────────────────────────

class SearchRequest(BaseModel):
    video_ids:             Optional[list[UUID]] = None
    person_ids:            Optional[list[UUID]] = None
    classes:               Optional[list[str]]  = None
    include_unknown_faces: bool                 = False
    date_from:             Optional[str]        = None   # ISO 8601
    date_to:               Optional[str]        = None   # ISO 8601
    min_confidence:        float                = 0.0
    page:                  int                  = 1
    page_size:             int                  = 20

    @field_validator("page")
    @classmethod
    def page_positive(cls, v: int) -> int:
        if v < 1:
            raise ValueError("page must be >= 1")
        return v

    @field_validator("page_size")
    @classmethod
    def page_size_range(cls, v: int) -> int:
        if not (1 <= v <= 100):
            raise ValueError("page_size must be 1–100")
        return v


class DetectionResult(BaseModel):
    class_name:  str
    confidence:  float
    bbox:        list[int]   # [x1, y1, x2, y2]


class FaceResult(BaseModel):
    face_detection_id:  int
    matched_person_id:  Optional[str]
    person_name:        Optional[str]
    match_tier:         Optional[str]
    match_similarity:   Optional[float]
    bbox:               list[int]   # [x1, y1, x2, y2]


class FrameResult(BaseModel):
    frame_id:      int
    video_id:      str
    ts_ms:         int
    thumbnail_url: str          # Always /frames/{id}/image — NOT a presigned URL
    detections:    list[DetectionResult]
    faces:         list[FaceResult]


class PaginationInfo(BaseModel):
    page:       int
    page_size:  int
    total:      int
    has_next:   bool


class SearchResponse(BaseModel):
    results:    list[FrameResult]
    pagination: PaginationInfo


# ── POST /search ──────────────────────────────────────────────────────────────

@router.post("", response_model=SearchResponse)
async def search_frames(body: SearchRequest) -> SearchResponse:
    """
    Search frames by any combination of filters.
    Returns paginated FrameResult list with YOLO detections and face matches.
    """
    pool = await get_pool()

    # Convert UUID lists to str lists for asyncpg
    video_ids_str  = [str(v) for v in body.video_ids]  if body.video_ids  else None
    person_ids_str = [str(p) for p in body.person_ids] if body.person_ids else None

    # ── Count query (for pagination total) ────────────────────────────────────
    count_sql = _build_search_sql(count_only=True)
    frame_sql = _build_search_sql(count_only=False)

    params = _build_params(body, video_ids_str, person_ids_str)
    count_params = params[:-2]  # remove LIMIT + OFFSET from count query

    async with pool.acquire() as conn:
        total_row = await conn.fetchrow(count_sql, *count_params)
        total = int(total_row["total"])

        rows = await conn.fetch(frame_sql, *params)

    if not rows:
        return SearchResponse(
            results=[],
            pagination=PaginationInfo(
                page=body.page,
                page_size=body.page_size,
                total=total,
                has_next=False,
            ),
        )

    frame_ids = [r["frame_id"] for r in rows]
    frame_map  = {r["frame_id"]: r for r in rows}

    # ── Fetch YOLO detections for matching frames ──────────────────────────────
    async with pool.acquire() as conn:
        det_rows = await conn.fetch(
            """
            SELECT frame_id, class_name, confidence,
                   bbox_x1, bbox_y1, bbox_x2, bbox_y2
            FROM detections
            WHERE frame_id = ANY($1::bigint[])
            """,
            frame_ids,
        )

    det_by_frame: dict[int, list[DetectionResult]] = {fid: [] for fid in frame_ids}
    for d in det_rows:
        det_by_frame[d["frame_id"]].append(
            DetectionResult(
                class_name=d["class_name"],
                confidence=float(d["confidence"]),
                bbox=[d["bbox_x1"], d["bbox_y1"], d["bbox_x2"], d["bbox_y2"]],
            )
        )

    # ── Fetch face detections for matching frames ──────────────────────────────
    async with pool.acquire() as conn:
        face_rows = await conn.fetch(
            """
            SELECT
                fd.id AS face_detection_id,
                fd.frame_id,
                fd.matched_person_id::text,
                fd.match_tier,
                fd.match_similarity,
                fd.bbox_x1, fd.bbox_y1, fd.bbox_x2, fd.bbox_y2,
                kp.name AS person_name
            FROM face_detections fd
            LEFT JOIN known_persons kp ON kp.id = fd.matched_person_id
            WHERE fd.frame_id = ANY($1::bigint[])
            """,
            frame_ids,
        )

    face_by_frame: dict[int, list[FaceResult]] = {fid: [] for fid in frame_ids}
    for f in face_rows:
        face_by_frame[f["frame_id"]].append(
            FaceResult(
                face_detection_id=f["face_detection_id"],
                matched_person_id=f["matched_person_id"],
                person_name=f["person_name"],
                match_tier=f["match_tier"],
                match_similarity=float(f["match_similarity"]) if f["match_similarity"] else None,
                bbox=[f["bbox_x1"], f["bbox_y1"], f["bbox_x2"], f["bbox_y2"]],
            )
        )

    # ── Assemble results ───────────────────────────────────────────────────────
    results = [
        FrameResult(
            frame_id=fid,
            video_id=str(frame_map[fid]["video_id"]),
            ts_ms=frame_map[fid]["ts_ms"],
            thumbnail_url=f"/frames/{fid}/image",   # on-demand presigned URL at redirect time
            detections=det_by_frame.get(fid, []),
            faces=face_by_frame.get(fid, []),
        )
        for fid in frame_ids
    ]

    return SearchResponse(
        results=results,
        pagination=PaginationInfo(
            page=body.page,
            page_size=body.page_size,
            total=total,
            has_next=(body.page * body.page_size) < total,
        ),
    )


# ── SQL builder helpers ───────────────────────────────────────────────────────

def _build_search_sql(count_only: bool) -> str:
    """
    Build the search SQL string.
    Parameters (positional):
      $1  video_ids      text[] | NULL
      $2  person_ids     text[] | NULL
      $3  classes        text[] | NULL
      $4  include_unknown_faces  bool
      $5  date_from      timestamptz | NULL
      $6  date_to        timestamptz | NULL
      $7  min_confidence float
      ($8 limit, $9 offset — count_only=False only)
    """
    select = (
        "SELECT COUNT(DISTINCT f.id) AS total"
        if count_only
        else """
        SELECT DISTINCT ON (f.id)
            f.id        AS frame_id,
            f.video_id,
            f.ts_ms
        """
    )
    sql = f"""
        {select}
        FROM frames f
        JOIN videos v ON v.id = f.video_id
        WHERE
            ($1::text[] IS NULL OR f.video_id::text = ANY($1))
            AND ($5::timestamptz IS NULL OR v.recorded_at >= $5::timestamptz)
            AND ($6::timestamptz IS NULL OR v.recorded_at <= $6::timestamptz)
            AND (
                $3::text[] IS NULL
                OR EXISTS (
                    SELECT 1 FROM detections d
                    WHERE d.frame_id = f.id
                      AND d.class_name = ANY($3)
                      AND d.confidence >= $7
                )
            )
            AND (
                $2::text[] IS NULL
                OR EXISTS (
                    SELECT 1 FROM face_detections fd2
                    WHERE fd2.frame_id = f.id
                      AND fd2.matched_person_id::text = ANY($2)
                )
            )
            AND (
                $4 IS FALSE
                OR EXISTS (
                    SELECT 1 FROM face_detections fd3
                    WHERE fd3.frame_id = f.id
                      AND fd3.matched_person_id IS NULL
                )
            )
    """
    if not count_only:
        sql += """
        ORDER BY f.id, v.recorded_at DESC NULLS LAST
        LIMIT $8 OFFSET $9
        """
    return sql


def _build_params(
    body: SearchRequest,
    video_ids_str: Optional[list[str]],
    person_ids_str: Optional[list[str]],
) -> list:
    """Return positional params list for the frame query (includes LIMIT + OFFSET)."""
    offset = (body.page - 1) * body.page_size
    return [
        video_ids_str,                          # $1
        person_ids_str,                         # $2
        body.classes,                           # $3
        body.include_unknown_faces,             # $4
        body.date_from,                         # $5
        body.date_to,                           # $6
        body.min_confidence,                    # $7
        body.page_size,                         # $8  (omitted for count)
        offset,                                 # $9  (omitted for count)
    ]
