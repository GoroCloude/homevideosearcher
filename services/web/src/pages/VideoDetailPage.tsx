import { useRef, useState } from 'react';
import { useNavigate, useParams, Link } from 'react-router-dom';
import { format, parseISO } from 'date-fns';
import { Dialog, DialogPanel, DialogTitle } from '@headlessui/react';
import clsx from 'clsx';
import {
  useVideoDetail,
  useVideoDetections,
  useVideoFaces,
  useDeleteVideo,
} from '../api/videos';
import { useSettings } from '../context/SettingsContext';
import { addToast } from '../hooks/useToast';

type Tab = 'detections' | 'faces';

function fmtDate(iso: string | null): string {
  if (!iso) return '—';
  try { return format(parseISO(iso), 'MMM d, yyyy HH:mm'); }
  catch { return iso; }
}

function fmtDuration(sec: number | null): string {
  if (sec == null) return '—';
  const m = Math.floor(sec / 60);
  const s = Math.floor(sec % 60);
  return `${m}:${String(s).padStart(2, '0')}`;
}

export default function VideoDetailPage() {
  const { id } = useParams<{ id: string }>();
  const navigate = useNavigate();
  const videoRef = useRef<HTMLVideoElement>(null);
  const [activeTab, setActiveTab] = useState<Tab>('detections');
  const [confirmOpen, setConfirmOpen] = useState(false);

  const { settings } = useSettings();
  const { data: video, isLoading, isError, error } = useVideoDetail(id ?? '');
  const { data: detections = [] } = useVideoDetections(id ?? '');
  const { data: faces = [] } = useVideoFaces(id ?? '');
  const deleteMutation = useDeleteVideo();

  // No-token guard — app-standard amber banner (matches VideosPage pattern)
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

  function seek(ts_ms: number) {
    if (videoRef.current) videoRef.current.currentTime = ts_ms / 1000;
  }

  async function handleConfirmDelete() {
    setConfirmOpen(false);
    try {
      await deleteMutation.mutateAsync(id!);
      addToast('Video deleted', 'success');
      navigate('/videos', { replace: true });
    } catch (err) {
      addToast(err instanceof Error ? err.message : 'Delete failed', 'error');
    }
  }

  // ── Loading ──────────────────────────────────────────────────────────────
  if (isLoading) {
    return (
      <div className="p-6 space-y-4">
        <div className="h-6 w-48 bg-gray-200 rounded animate-pulse" />
        <div className="h-56 bg-gray-200 rounded animate-pulse" />
        <div className="h-40 bg-gray-200 rounded animate-pulse" />
      </div>
    );
  }

  // ── Error / not found ────────────────────────────────────────────────────
  if (isError || !video) {
    return (
      <div className="p-6">
        <div className="bg-red-50 border border-red-200 rounded-lg p-4 text-sm text-red-700">
          Failed to load video:{' '}
          {error instanceof Error ? error.message : 'Not found'}
        </div>
        <button
          onClick={() => navigate('/videos')}
          className="mt-4 text-sm text-blue-600 hover:underline"
        >
          ← Back to Videos
        </button>
      </div>
    );
  }

  // ── Page ─────────────────────────────────────────────────────────────────
  return (
    <div className="p-4 md:p-6 max-w-4xl mx-auto space-y-6">

      {/* Back link */}
      <button
        onClick={() => navigate('/videos')}
        className="text-sm text-blue-600 hover:underline"
      >
        ← Back to Videos
      </button>

      {/* Metadata header */}
      <div className="bg-white border border-gray-200 rounded-xl p-5 shadow-sm">
        <h1 className="text-base font-semibold text-gray-900 font-mono break-all mb-4">
          {video.filename}
        </h1>
        <dl className="grid grid-cols-2 sm:grid-cols-4 gap-x-6 gap-y-3 text-sm">
          <div>
            <dt className="text-xs uppercase tracking-wide text-gray-400 mb-0.5">Status</dt>
            <dd className="text-gray-800 capitalize">{video.status}</dd>
          </div>
          <div>
            <dt className="text-xs uppercase tracking-wide text-gray-400 mb-0.5">Duration</dt>
            <dd className="text-gray-800">{fmtDuration(video.duration_sec)}</dd>
          </div>
          <div>
            <dt className="text-xs uppercase tracking-wide text-gray-400 mb-0.5">Recorded</dt>
            <dd className="text-gray-800">{fmtDate(video.recorded_at)}</dd>
          </div>
          <div>
            <dt className="text-xs uppercase tracking-wide text-gray-400 mb-0.5">Ingested</dt>
            <dd className="text-gray-800">{fmtDate(video.ingested_at)}</dd>
          </div>
        </dl>
      </div>

      {/* Video player */}
      <div className="bg-black rounded-xl overflow-hidden shadow-sm">
        <video
          ref={videoRef}
          src={video.stream_url}
          controls
          className="w-full max-h-96"
        />
      </div>

      {/* Tabs */}
      <div>
        <div className="flex gap-1 border-b border-gray-200 mb-4">
          {(['detections', 'faces'] as Tab[]).map(tab => (
            <button
              key={tab}
              onClick={() => setActiveTab(tab)}
              className={clsx(
                'px-4 py-2 text-sm font-medium capitalize transition-colors',
                activeTab === tab
                  ? 'border-b-2 border-blue-600 text-blue-700'
                  : 'text-gray-500 hover:text-gray-700',
              )}
            >
              {tab === 'detections'
                ? `Detections (${detections.length})`
                : `Faces (${faces.length})`}
            </button>
          ))}
        </div>

        {/* Detections tab */}
        {activeTab === 'detections' && (
          <>
            {detections.length === 0 ? (
              <p className="text-sm text-gray-400 italic py-8 text-center">
                No detections recorded for this video.
              </p>
            ) : (
              <div className="grid grid-cols-2 sm:grid-cols-3 md:grid-cols-4 gap-3">
                {detections.map(det => (
                  <div
                    key={det.id}
                    className="bg-white border border-gray-200 rounded-lg overflow-hidden shadow-sm"
                  >
                    <div className="aspect-video bg-gray-100 overflow-hidden">
                      <img
                        src={det.thumbnail_url}
                        alt={`${det.label} at ${(det.ts_ms / 1000).toFixed(1)}s`}
                        loading="lazy"
                        className="w-full h-full object-cover"
                      />
                    </div>
                    <div className="p-2 space-y-0.5">
                      <p className="text-xs font-medium text-gray-800 truncate capitalize">
                        {det.label}
                      </p>
                      <p className="text-xs text-gray-500">
                        {Math.round(det.confidence * 100)}% · {(det.ts_ms / 1000).toFixed(1)}s
                      </p>
                    </div>
                  </div>
                ))}
              </div>
            )}
          </>
        )}

        {/* Faces tab */}
        {activeTab === 'faces' && (
          <>
            {/* Timeline bar — only rendered when there are faces and duration is known */}
            {faces.length > 0 && video.duration_sec != null && (
              <div className="mb-4">
                <p className="text-xs text-gray-400 mb-1">Timeline — click to seek</p>
                <div className="relative h-8 bg-gray-100 rounded-full overflow-hidden w-full">
                  {faces.map(f => (
                    <button
                      key={f.id}
                      className="absolute top-0 h-full w-1 bg-blue-500 hover:bg-blue-700 transition-colors"
                      style={{
                        left: `${(f.ts_ms / (video.duration_sec! * 1000)) * 100}%`,
                      }}
                      onClick={() => seek(f.ts_ms)}
                      title={`${f.person_name} at ${(f.ts_ms / 1000).toFixed(1)}s`}
                    />
                  ))}
                </div>
              </div>
            )}

            {faces.length === 0 ? (
              <p className="text-sm text-gray-400 italic py-8 text-center">
                No faces recorded for this video.
              </p>
            ) : (
              <div className="grid grid-cols-2 sm:grid-cols-3 md:grid-cols-4 gap-3">
                {faces.map(face => (
                  <div
                    key={face.id}
                    className="bg-white border border-gray-200 rounded-lg overflow-hidden shadow-sm"
                  >
                    <div className="aspect-square bg-gray-100 overflow-hidden">
                      <img
                        src={face.thumbnail_url}
                        alt={`${face.person_name} at ${(face.ts_ms / 1000).toFixed(1)}s`}
                        loading="lazy"
                        className="w-full h-full object-cover"
                      />
                    </div>
                    <div className="p-2 space-y-0.5">
                      <p className="text-xs font-medium text-gray-800 truncate">
                        {face.person_name}
                      </p>
                      <p className="text-xs text-gray-500">
                        {(face.ts_ms / 1000).toFixed(1)}s
                      </p>
                    </div>
                  </div>
                ))}
              </div>
            )}
          </>
        )}
      </div>

      {/* Delete button */}
      <div className="pt-2 border-t border-gray-100 flex justify-end">
        <button
          onClick={() => setConfirmOpen(true)}
          disabled={deleteMutation.isPending}
          className="px-4 py-2 text-sm font-medium text-red-600 border border-red-200 rounded-lg hover:bg-red-50 disabled:opacity-50 disabled:cursor-not-allowed transition-colors"
        >
          {deleteMutation.isPending ? 'Deleting…' : 'Delete Video'}
        </button>
      </div>

      {/* Confirmation dialog */}
      <Dialog open={confirmOpen} onClose={() => setConfirmOpen(false)}>
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
                onClick={() => setConfirmOpen(false)}
                className="px-3 py-1.5 text-sm text-gray-600 hover:text-gray-800"
              >
                Cancel
              </button>
              <button
                onClick={handleConfirmDelete}
                className="px-3 py-1.5 text-sm bg-red-600 text-white rounded-lg hover:bg-red-700"
              >
                Delete
              </button>
            </div>
          </DialogPanel>
        </div>
      </Dialog>

    </div>
  );
}
