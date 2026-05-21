"""
Tests for match_face_embedding — two-tier similarity threshold logic.

Threshold rules (configurable via env; defaults tested here):
  similarity >= 0.65 (HIGH) → (person_id, similarity, 'confident')
  0.50 <= similarity < 0.65 → (person_id, similarity, 'probable')
  similarity < 0.50 (LOW)   → (None, similarity, None)   — genuine unknown
  no persons enrolled        → (None, None, None)

asyncpg pool is mocked throughout — no DB required.

Run from services/ingestion-worker/:
    python -m pytest tests/test_face_threshold.py -v
"""
from unittest.mock import AsyncMock, MagicMock

import pytest

from app.faces import match_face_embedding


# ── Mock helpers ──────────────────────────────────────────────────────────────

_PERSON_ID = "123e4567-e89b-12d3-a456-426614174000"


def _make_pool(similarity: float | None = None):
    """
    Return a mock asyncpg pool whose single fetchrow() returns either:
      - None          (no enrolled persons)
      - a row with the given similarity value
    """
    conn = AsyncMock()
    if similarity is None:
        conn.fetchrow.return_value = None
    else:
        conn.fetchrow.return_value = {
            "person_id": _PERSON_ID,
            "similarity": similarity,
        }

    acquire_cm = MagicMock()
    acquire_cm.__aenter__ = AsyncMock(return_value=conn)
    acquire_cm.__aexit__ = AsyncMock(return_value=False)

    pool = MagicMock()
    pool.acquire.return_value = acquire_cm
    return pool


_DUMMY_EMB = [0.0] * 512


# ── Threshold tiers ───────────────────────────────────────────────────────────

class TestTwoTierThreshold:
    async def test_similarity_well_above_high_threshold_returns_confident(self):
        pool = _make_pool(similarity=0.90)
        person_id, sim, tier = await match_face_embedding(_DUMMY_EMB, pool)
        assert tier == "confident"
        assert person_id == _PERSON_ID
        assert abs(sim - 0.90) < 1e-6

    async def test_similarity_exactly_at_high_threshold_returns_confident(self):
        """Boundary: 0.65 is the minimum 'confident' similarity."""
        pool = _make_pool(similarity=0.65)
        _, _, tier = await match_face_embedding(_DUMMY_EMB, pool)
        assert tier == "confident"

    async def test_similarity_just_below_high_threshold_returns_probable(self):
        pool = _make_pool(similarity=0.6499)
        _, _, tier = await match_face_embedding(_DUMMY_EMB, pool)
        assert tier == "probable"

    async def test_similarity_in_middle_of_probable_range(self):
        pool = _make_pool(similarity=0.57)
        person_id, sim, tier = await match_face_embedding(_DUMMY_EMB, pool)
        assert tier == "probable"
        assert person_id == _PERSON_ID
        assert abs(sim - 0.57) < 1e-6

    async def test_similarity_exactly_at_low_threshold_returns_probable(self):
        """Boundary: 0.50 is the minimum 'probable' similarity."""
        pool = _make_pool(similarity=0.50)
        _, _, tier = await match_face_embedding(_DUMMY_EMB, pool)
        assert tier == "probable"

    async def test_similarity_just_below_low_threshold_returns_unknown(self):
        pool = _make_pool(similarity=0.4999)
        person_id, sim, tier = await match_face_embedding(_DUMMY_EMB, pool)
        assert tier is None
        assert person_id is None

    async def test_similarity_well_below_low_threshold_returns_unknown(self):
        pool = _make_pool(similarity=0.10)
        person_id, sim, tier = await match_face_embedding(_DUMMY_EMB, pool)
        assert person_id is None
        assert tier is None


# ── Similarity stored even for unknowns ──────────────────────────────────────

class TestSimilarityAuditTrail:
    async def test_below_threshold_still_returns_similarity_value(self):
        """
        Even when the face is 'unknown' (below LOW threshold), the similarity
        is still returned so it can be stored in match_similarity for audit/HDBSCAN.
        """
        pool = _make_pool(similarity=0.30)
        person_id, sim, tier = await match_face_embedding(_DUMMY_EMB, pool)
        assert person_id is None
        assert tier is None
        assert abs(sim - 0.30) < 1e-6  # similarity present, not None

    async def test_no_enrolled_persons_returns_all_none(self):
        """No rows in person_embeddings → all three values must be None."""
        pool = _make_pool(similarity=None)  # fetchrow returns None
        person_id, sim, tier = await match_face_embedding(_DUMMY_EMB, pool)
        assert person_id is None
        assert sim is None
        assert tier is None


# ── Return types ──────────────────────────────────────────────────────────────

class TestReturnTypes:
    async def test_confident_match_return_types(self):
        pool = _make_pool(similarity=0.80)
        person_id, sim, tier = await match_face_embedding(_DUMMY_EMB, pool)
        assert isinstance(person_id, str)
        assert isinstance(sim, float)
        assert isinstance(tier, str)

    async def test_probable_match_return_types(self):
        pool = _make_pool(similarity=0.55)
        person_id, sim, tier = await match_face_embedding(_DUMMY_EMB, pool)
        assert isinstance(person_id, str)
        assert isinstance(sim, float)
        assert isinstance(tier, str)

    async def test_unknown_match_none_types(self):
        pool = _make_pool(similarity=0.30)
        person_id, sim, tier = await match_face_embedding(_DUMMY_EMB, pool)
        assert person_id is None
        assert sim is not None   # similarity is always returned
        assert tier is None
