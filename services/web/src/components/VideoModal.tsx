import { useState } from 'react';
import { Dialog, DialogPanel, DialogTitle } from '@headlessui/react';
import type { FrameResult } from '../types/api';
import { authFetch } from '../api/client';
import FrameThumbnail from './FrameThumbnail';
import clsx from 'clsx';

interface Props {
  frame:   FrameResult | null;
  onClose: () => void;
}

const TIER_LABEL: Record<string, string> = {
  confident: 'Confident match',
  probable:  'Probable match',
};

const TIER_COLOR: Record<string, string> = {
  confident: 'bg-green-100 text-green-800',
  probable:  'bg-yellow-100 text-yellow-800',
};

export default function VideoModal({ frame, onClose }: Props) {
  const [playLoading, setPlayLoading] = useState(false);
  const [playError,   setPlayError]   = useState<string | null>(null);

  if (!frame) return null;

  async function handlePlay() {
    if (!frame) return;
    setPlayLoading(true);
    setPlayError(null);
    try {
      const data = await authFetch(`/videos/${frame.video_id}/stream-url`).then(r => r.json());
      const seconds = (frame.ts_ms / 1000).toFixed(3);
      window.open(`${data.url}#t=${seconds}`, '_blank', 'noopener,noreferrer');
    } catch (err) {
      setPlayError(err instanceof Error ? err.message : 'Failed to get video URL');
    } finally {
      setPlayLoading(false);
    }
  }

  const hasContent = frame.detections.length > 0 || frame.faces.length > 0;

  return (
    <Dialog open={!!frame} onClose={onClose} className="relative z-50">
      {/* Backdrop */}
      <div className="fixed inset-0 bg-black/60" aria-hidden="true" />

      {/* Panel */}
      <div className="fixed inset-0 flex items-center justify-center p-4">
        <DialogPanel className="bg-white rounded-xl shadow-2xl max-w-2xl w-full max-h-[90vh] overflow-y-auto">

          {/* Header */}
          <div className="flex items-center justify-between px-5 py-4 border-b border-gray-100">
            <DialogTitle className="text-sm font-semibold text-gray-800">
              Frame at {(frame.ts_ms / 1000).toFixed(1)}s
            </DialogTitle>
            <button
              onClick={onClose}
              className="text-gray-400 hover:text-gray-600 text-xl leading-none"
              aria-label="Close"
            >
              ×
            </button>
          </div>

          {/* Thumbnail */}
          <div className="px-5 pt-4">
            <FrameThumbnail
              frameId={frame.frame_id}
              alt={`Frame at ${frame.ts_ms}ms`}
              className="w-full aspect-video rounded"
            />
          </div>

          {/* Detections */}
          {frame.detections.length > 0 && (
            <div className="px-5 pt-4">
              <h3 className="text-xs font-semibold uppercase tracking-wide text-gray-500 mb-2">
                Detections
              </h3>
              <div className="flex flex-wrap gap-1.5">
                {frame.detections.map((det, i) => (
                  <span
                    key={i}
                    className="inline-flex items-center px-2 py-0.5 rounded text-xs bg-gray-100 text-gray-700"
                  >
                    {det.class_name}
                    <span className="ml-1 text-gray-400">{Math.round(det.confidence * 100)}%</span>
                  </span>
                ))}
              </div>
            </div>
          )}

          {/* Faces */}
          {frame.faces.length > 0 && (
            <div className="px-5 pt-3">
              <h3 className="text-xs font-semibold uppercase tracking-wide text-gray-500 mb-2">
                Faces
              </h3>
              <div className="space-y-1.5">
                {frame.faces.map((face) => (
                  <div key={face.face_detection_id} className="flex items-center gap-2 text-sm">
                    {face.person_name ? (
                      <>
                        <span className="font-medium text-gray-800">{face.person_name}</span>
                        {face.match_tier && (
                          <span className={clsx('text-xs px-1.5 py-0.5 rounded', TIER_COLOR[face.match_tier] ?? 'bg-gray-100')}>
                            {TIER_LABEL[face.match_tier] ?? face.match_tier}
                          </span>
                        )}
                        {face.match_similarity && (
                          <span className="text-xs text-gray-400">
                            {(face.match_similarity * 100).toFixed(0)}% sim
                          </span>
                        )}
                      </>
                    ) : (
                      <span className="text-gray-400 italic">Unknown face</span>
                    )}
                  </div>
                ))}
              </div>
            </div>
          )}

          {!hasContent && (
            <p className="px-5 pt-4 text-sm text-gray-400 italic">No detections in this frame.</p>
          )}

          {/* Play in video */}
          <div className="px-5 py-4 mt-2 border-t border-gray-100 flex items-center gap-3">
            <button
              onClick={handlePlay}
              disabled={playLoading}
              className="inline-flex items-center gap-2 px-4 py-2 bg-blue-600 text-white text-sm font-medium rounded-lg hover:bg-blue-700 disabled:opacity-50 disabled:cursor-not-allowed transition-colors"
            >
              {playLoading ? '⏳ Loading…' : '▶ Play in video'}
            </button>
            {playError && (
              <span className="text-xs text-red-600">{playError}</span>
            )}
            <span className="text-xs text-gray-400 ml-auto">Opens in new tab</span>
          </div>

        </DialogPanel>
      </div>
    </Dialog>
  );
}
