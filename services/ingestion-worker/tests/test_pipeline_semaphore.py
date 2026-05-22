"""
Tests: asyncio.Semaphore(1) in pipeline.py serializes process_video calls.

RED phase: these tests MUST FAIL before the semaphore is added to pipeline.py.
GREEN phase: pass after _pipeline_sem + async with block are added.

Run from services/ingestion-worker/:
    python -m pytest tests/test_pipeline_semaphore.py -v
"""
import asyncio
from unittest.mock import AsyncMock, patch

import app.pipeline as pipeline


class TestSemaphoreExists:
    def test_pipeline_sem_attribute_exists(self):
        """_pipeline_sem must be a module-level attribute of pipeline.py."""
        assert hasattr(pipeline, "_pipeline_sem"), (
            "_pipeline_sem not found — add `_pipeline_sem = asyncio.Semaphore(1)` "
            "at module level in pipeline.py (after the '# ── Main pipeline' banner)"
        )

    def test_pipeline_sem_is_asyncio_semaphore(self):
        assert isinstance(pipeline._pipeline_sem, asyncio.Semaphore)

    def test_pipeline_sem_initial_value_is_one(self):
        """Semaphore must start unlocked with exactly 1 slot."""
        assert pipeline._pipeline_sem._value == 1


class TestSemaphoreSerializes:
    """Two concurrent process_video calls must NOT overlap."""

    async def test_concurrent_calls_execute_sequentially(self):
        """
        Timeline with semaphore:   start:aaa, end:aaa, start:bbb, end:bbb
        Timeline WITHOUT semaphore: start:aaa, start:bbb, end:aaa, end:bbb  (BAD)
        """
        timeline: list[str] = []

        # Reset semaphore to a fresh one so test isolation is guaranteed
        original_sem = pipeline._pipeline_sem
        pipeline._pipeline_sem = asyncio.Semaphore(1)

        try:
            async def mock_update_status(video_id, status, error_message=None):
                if status == "processing":
                    timeline.append(f"start:{video_id}")
                    await asyncio.sleep(0.03)   # hold the slot briefly
                elif status in ("done", "failed"):
                    timeline.append(f"end:{video_id}")

            with (
                patch("app.pipeline.update_video_status", side_effect=mock_update_status),
                patch("app.pipeline.download_video"),
                patch("app.pipeline.probe_video_metadata", return_value={}),
                patch("app.pipeline.extract_frames", return_value=[]),
                patch("app.pipeline.get_pool", new_callable=AsyncMock),
            ):
                t1 = asyncio.create_task(
                    pipeline.process_video("aaa", "videos/a.mp4", None, None)
                )
                t2 = asyncio.create_task(
                    pipeline.process_video("bbb", "videos/b.mp4", None, None)
                )
                await asyncio.gather(t1, t2, return_exceptions=True)

            assert len(timeline) == 4, f"Expected 4 events, got: {timeline}"
            # Sequential invariant: first job fully completes before second starts
            assert timeline.index("end:aaa") < timeline.index("start:bbb"), (
                f"Concurrent execution detected — timeline: {timeline}\n"
                "Ensure process_video body is wrapped in `async with _pipeline_sem:`"
            )
        finally:
            pipeline._pipeline_sem = original_sem
