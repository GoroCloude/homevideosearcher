import React, { useState } from 'react';
import { useQueryClient } from '@tanstack/react-query';
import { Link, useNavigate } from 'react-router-dom';
import { format, parseISO } from 'date-fns';
import { useVideos, useReIngestVideo, useDeleteVideo } from '../api/videos';
import { Dialog, DialogPanel, DialogTitle } from '@headlessui/react';
import { addToast } from '../hooks/useToast';
import { useSettings } from '../context/SettingsContext';
import StatusBadge from '../components/StatusBadge';
import VideoUploadButton from '../components/VideoUploadButton';
import type { VideoListItem } from '../types/api';

function shortKey(minioKey: string): string {
  return minioKey.split('/').pop() ?? minioKey;
}

function fmtDate(iso: string | null): string {
  if (!iso) return '—';
  try { return format(parseISO(iso), 'MMM d, yyyy HH:mm'); }
  catch { return iso; }
}

function dayKey(recorded: string | null, ingested: string): string {
  const src = recorded ?? ingested;
  try { return format(parseISO(src), 'yyyy-MM-dd'); }
  catch { return ingested.slice(0, 10); }
}

function dayLabel(key: string): string {
  try {
    const d = parseISO(key);
    const today = format(new Date(), 'yyyy-MM-dd');
    const yesterday = format(new Date(Date.now() - 86400000), 'yyyy-MM-dd');
    if (key === today) return `Today · ${format(d, 'MMMM d, yyyy')}`;
    if (key === yesterday) return `Yesterday · ${format(d, 'MMMM d, yyyy')}`;
    return format(d, 'EEEE, MMMM d, yyyy');
  } catch { return key; }
}

function groupByDay(videos: VideoListItem[]): Array<{ key: string; label: string; videos: VideoListItem[] }> {
  const groups: Array<{ key: string; label: string; videos: VideoListItem[] }> = [];
  const seen = new Map<string, (typeof groups)[0]>();
  for (const v of videos) {
    const key = dayKey(v.recorded_at, v.ingested_at);
    if (!seen.has(key)) {
      const g = { key, label: dayLabel(key), videos: [] as VideoListItem[] };
      seen.set(key, g);
      groups.push(g);
    }
    seen.get(key)!.videos.push(v);
  }
  return groups;
}

export default function VideosPage() {
  const { settings } = useSettings();
  const [page, setPage] = useState(1);

  const { data, isLoading, isError, error } = useVideos(page);
  const reIngest = useReIngestVideo();

  const [reingestingId, setReingestingId] = useState<string | null>(null);
  const qc = useQueryClient();
  const [uploadProgress, setUploadProgress] = useState(0);
  const navigate = useNavigate();
  const deleteMutation = useDeleteVideo();
  const [deleteTarget, setDeleteTarget] = useState<string | null>(null);
  const [collapsedDays, setCollapsedDays] = useState<Set<string>>(new Set());

  function toggleDay(key: string) {
    setCollapsedDays(prev => {
      const next = new Set(prev);
      next.has(key) ? next.delete(key) : next.add(key);
      return next;
    });
  }

  // No-token banner
  if (!settings.apiToken) {
    return (
      <div className="p-6">
        <div className="bg-amber-50 border border-amber-200 rounded-lg p-4 text-sm text-amber-800">
          API token not configured.{' '}
          <Link to="/settings" className="font-medium underline">Go to Settings →</Link>
        </div>
      </div>
    );
  }

  async function handleReIngest(id: string, minioKey: string) {
    setReingestingId(id);
    try {
      await reIngest.mutateAsync(minioKey);
    } finally {
      setReingestingId(null);
    }
  }

  async function handleDelete(id: string) {
    setDeleteTarget(null);
    try {
      await deleteMutation.mutateAsync(id);
      addToast('Video deleted', 'success');
    } catch (err) {
      addToast(err instanceof Error ? err.message : 'Delete failed', 'error');
    }
  }

  return (
    <div className="p-4 md:p-6">
      <div className="flex items-center justify-between mb-5">
        <h1 className="text-lg font-semibold text-gray-900">Videos</h1>
        <div className="flex items-center gap-3">
          {data && (
            <span className="text-sm text-gray-500">{data.total} video{data.total !== 1 ? 's' : ''}</span>
          )}
          <VideoUploadButton
            onUploadComplete={() => qc.invalidateQueries({ queryKey: ['videos'] })}
            onProgressChange={setUploadProgress}
          />
        </div>
      </div>

      {/* Progress bar — D-07: h-1 thin bar between header row and table content.
          D-09: only rendered when pct > 0 (hidden when idle or after queue resets to 0). */}
      {uploadProgress > 0 && uploadProgress < 100 && (
        <div className="h-1 w-full bg-gray-200 rounded-full mb-5 overflow-hidden">
          <div
            className="h-1 bg-blue-500 rounded-full transition-all duration-150"
            style={{ width: `${uploadProgress}%` }}
          />
        </div>
      )}

      {/* Loading */}
      {isLoading && (
        <div className="space-y-2">
          {Array.from({ length: 5 }).map((_, i) => (
            <div key={i} className="h-12 bg-gray-200 rounded animate-pulse" />
          ))}
        </div>
      )}

      {/* Error */}
      {isError && (
        <div className="bg-red-50 border border-red-200 rounded-lg p-4 text-sm text-red-700">
          Failed to load videos: {error instanceof Error ? error.message : 'Unknown error'}
        </div>
      )}

      {/* Empty */}
      {!isLoading && !isError && data?.results.length === 0 && (
        <div className="flex flex-col items-center py-20 text-gray-400">
          <span className="text-4xl mb-3">🎬</span>
          <p className="text-sm">No videos ingested yet</p>
        </div>
      )}

      {/* Table */}
      {data && data.results.length > 0 && (
        <>
          <div className="overflow-x-auto rounded-lg border border-gray-200 shadow-sm">
            <table className="w-full text-sm text-left">
              <thead className="bg-gray-50 text-xs uppercase tracking-wide text-gray-500">
                <tr>
                  <th className="px-4 py-3">File</th>
                  <th className="px-4 py-3">Status</th>
                  <th className="px-4 py-3 hidden sm:table-cell">Frames</th>
                  <th className="px-4 py-3 hidden sm:table-cell">Detections</th>
                  <th className="px-4 py-3 hidden md:table-cell">Faces</th>
                  <th className="px-4 py-3 hidden lg:table-cell">Ingested</th>
                  <th className="px-4 py-3">Action</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-gray-100">
                {groupByDay(data.results).map(group => (
                  <React.Fragment key={group.key}>
                    {/* Day group header */}
                    <tr
                      className="bg-gray-50 border-t-2 border-gray-200 cursor-pointer select-none hover:bg-gray-100 transition-colors"
                      onClick={() => toggleDay(group.key)}
                    >
                      <td colSpan={7} className="px-4 py-2 text-xs font-semibold text-gray-500 uppercase tracking-wider">
                        <span className="mr-2 text-gray-400">
                          {collapsedDays.has(group.key) ? '▶' : '▼'}
                        </span>
                        {group.label}
                        <span className="ml-2 font-normal normal-case text-gray-400">
                          {group.videos.length} video{group.videos.length !== 1 ? 's' : ''}
                        </span>
                      </td>
                    </tr>
                    {!collapsedDays.has(group.key) && group.videos.map(video => (
                      <React.Fragment key={video.id}>
                        <tr
                          className="hover:bg-gray-50 transition-colors cursor-pointer"
                          onClick={() => navigate(`/videos/${video.id}`)}
                        >
                          <td className="px-4 py-3 font-mono text-xs text-gray-700 max-w-xs truncate">
                            {shortKey(video.minio_key)}
                          </td>
                          <td className="px-4 py-3">
                            <StatusBadge status={video.status} />
                          </td>
                          <td className="px-4 py-3 text-gray-600 hidden sm:table-cell">
                            {video.frame_count.toLocaleString()}
                          </td>
                          <td className="px-4 py-3 text-gray-600 hidden sm:table-cell">
                            {video.detection_count.toLocaleString()}
                          </td>
                          <td className="px-4 py-3 text-gray-600 hidden md:table-cell">
                            {video.face_count.toLocaleString()}
                          </td>
                          <td className="px-4 py-3 text-gray-500 hidden lg:table-cell whitespace-nowrap">
                            {fmtDate(video.ingested_at)}
                          </td>
                          <td className="px-4 py-3">
                            <div className="flex items-center gap-2">
                              <button
                                onClick={(e) => { e.stopPropagation(); handleReIngest(video.id, video.minio_key); }}
                                disabled={video.status === 'processing' || reingestingId === video.id}
                                className="text-xs text-blue-600 hover:text-blue-800 disabled:text-gray-400 disabled:cursor-not-allowed font-medium"
                              >
                                {reingestingId === video.id ? 'Starting…' : 'Re-ingest'}
                              </button>

                              <button
                                onClick={(e) => { e.stopPropagation(); navigate(`/videos/${video.id}`); }}
                                className="text-gray-400 hover:text-gray-700 text-base leading-none"
                                title="View detail"
                                aria-label="View video detail"
                              >
                                ↗
                              </button>

                              <button
                                onClick={(e) => { e.stopPropagation(); setDeleteTarget(video.id); }}
                                disabled={deleteMutation.isPending && deleteTarget === video.id}
                                className="text-xs text-red-500 hover:text-red-700 disabled:text-gray-400 disabled:cursor-not-allowed font-medium"
                              >
                                Delete
                              </button>
                            </div>
                          </td>
                        </tr>
                        {/* Error detail row */}
                        {video.status === 'failed' && video.error_message && (
                          <tr className="bg-red-50">
                            <td colSpan={7} className="px-4 py-2 text-xs text-red-600">
                              Error: {video.error_message}
                            </td>
                          </tr>
                        )}
                      </React.Fragment>
                    ))}
                  </React.Fragment>
                ))}
              </tbody>
            </table>
          </div>

          {/* Pagination */}
          {data.total > data.page_size && (
            <div className="flex items-center justify-center gap-3 mt-4">
              <button
                onClick={() => setPage(p => p - 1)}
                disabled={page <= 1}
                className="px-3 py-1.5 text-sm border rounded disabled:opacity-40 hover:bg-gray-50"
              >
                ← Prev
              </button>
              <span className="text-sm text-gray-600">
                Page {page} · {data.total} total
              </span>
              <button
                onClick={() => setPage(p => p + 1)}
                disabled={!data.has_next}
                className="px-3 py-1.5 text-sm border rounded disabled:opacity-40 hover:bg-gray-50"
              >
                Next →
              </button>
            </div>
          )}
        </>
      )}
      {/* Delete confirmation dialog */}
      <Dialog open={deleteTarget !== null} onClose={() => setDeleteTarget(null)}>
        <div className="fixed inset-0 bg-black/40 z-50" />
        <div className="fixed inset-0 flex items-center justify-center z-50 p-4">
          <DialogPanel className="bg-white rounded-xl p-6 max-w-sm w-full shadow-xl">
            <DialogTitle className="text-base font-semibold text-gray-900">
              Delete this video?
            </DialogTitle>
            <p className="mt-2 text-sm text-gray-600">
              This will permanently remove the video, all detections, and all face records.
              This cannot be undone.
            </p>
            <div className="mt-4 flex justify-end gap-2">
              <button
                onClick={() => setDeleteTarget(null)}
                className="px-3 py-1.5 text-sm text-gray-600 hover:text-gray-800"
              >
                Cancel
              </button>
              <button
                onClick={() => deleteTarget && handleDelete(deleteTarget)}
                disabled={deleteMutation.isPending}
                className="px-3 py-1.5 text-sm bg-red-600 text-white rounded-lg hover:bg-red-700 disabled:opacity-50"
              >
                {deleteMutation.isPending ? 'Deleting…' : 'Delete'}
              </button>
            </div>
          </DialogPanel>
        </div>
      </Dialog>
    </div>
  );
}
