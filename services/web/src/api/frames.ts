/**
 * Build the URL for a frame thumbnail image.
 * No auth needed — frames router is public after Phase 4 fix (Plan 01, Task 1).
 * Usage: <img src={getFrameImageUrl(frameId)} loading="lazy" />
 */
export function getFrameImageUrl(frameId: number): string {
  return `/api/frames/${frameId}/image`;
}
