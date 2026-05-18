import { useState } from 'react';
import { format, parseISO } from 'date-fns';
import type { ClusterItem } from '../types/api';
import { useCreatePerson, useRematchPerson } from '../api/persons';
import FrameThumbnail from './FrameThumbnail';

interface Props {
  cluster:   ClusterItem;
  onEnrolled?: () => void;   // called after successful enroll + rematch
}

function fmtDate(iso: string | null): string {
  if (!iso) return '—';
  try { return format(parseISO(iso), 'MMM d, yyyy'); }
  catch { return iso; }
}

export default function ClusterCard({ cluster, onEnrolled }: Props) {
  const [enrolling,   setEnrolling]   = useState(false);
  const [personName,  setPersonName]  = useState('');
  const [enrollError, setEnrollError] = useState<string | null>(null);
  const [enrollDone,  setEnrollDone]  = useState(false);

  const createPerson  = useCreatePerson();
  const rematchPerson = useRematchPerson();

  async function handleEnroll(e: React.FormEvent) {
    e.preventDefault();
    const name = personName.trim();
    if (!name) return;

    setEnrollError(null);
    try {
      // Step 1: Create the person
      const person = await createPerson.mutateAsync(name);

      // Step 2: Rematch using the new person ID
      // This retroactively matches all stored embeddings for this cluster's faces
      await rematchPerson.mutateAsync(person.id);

      setEnrollDone(true);
      setEnrolling(false);
      onEnrolled?.();
    } catch (err) {
      setEnrollError(err instanceof Error ? err.message : 'Enroll failed');
    }
  }

  const isPending = createPerson.isPending || rematchPerson.isPending;

  return (
    <div className="bg-white border border-gray-200 rounded-xl overflow-hidden shadow-sm flex flex-col">
      {/* Thumbnail */}
      <div className="relative">
        {cluster.representative_frame_id ? (
          <FrameThumbnail
            frameId={cluster.representative_frame_id}
            alt="Cluster representative"
            className="w-full aspect-video"
          />
        ) : (
          <div className="w-full aspect-video bg-gray-100 flex items-center justify-center">
            <span className="text-3xl text-gray-300">👤</span>
          </div>
        )}
        {/* Appearance count badge */}
        <span className="absolute top-2 right-2 bg-black/60 text-white text-xs font-medium px-2 py-0.5 rounded-full">
          {cluster.appearance_count}× seen
        </span>
      </div>

      {/* Body */}
      <div className="p-3 flex flex-col gap-2 flex-1">
        <div className="text-xs text-gray-500 space-y-0.5">
          <p>First seen: <span className="text-gray-700">{fmtDate(cluster.first_seen)}</span></p>
          <p>Last seen:  <span className="text-gray-700">{fmtDate(cluster.last_seen)}</span></p>
        </div>

        {/* Actions */}
        {enrollDone ? (
          <div className="text-xs text-green-700 bg-green-50 border border-green-200 rounded px-2 py-1 text-center">
            ✓ Enrolled as person
          </div>
        ) : (
          <div className="flex gap-2 mt-auto">
            <button
              onClick={() => { setEnrolling(v => !v); setEnrollError(null); }}
              className="flex-1 text-xs font-medium text-blue-600 hover:text-blue-800 border border-blue-200 rounded px-2 py-1.5 transition-colors"
            >
              {enrolling ? 'Cancel' : '+ Enroll as person'}
            </button>
            <button
              disabled
              title="Coming soon — Phase 3"
              className="text-xs text-gray-400 border border-gray-200 rounded px-2 py-1.5 cursor-not-allowed"
            >
              🚫 Noise
            </button>
          </div>
        )}

        {/* Enroll name form */}
        {enrolling && !enrollDone && (
          <form onSubmit={handleEnroll} className="flex gap-2 mt-1">
            <input
              type="text"
              value={personName}
              onChange={e => { setPersonName(e.target.value); setEnrollError(null); }}
              placeholder="Name…"
              required
              autoFocus
              className="flex-1 text-xs border border-gray-300 rounded px-2 py-1 focus:outline-none focus:ring-2 focus:ring-blue-500"
            />
            <button
              type="submit"
              disabled={isPending || !personName.trim()}
              className="text-xs font-medium bg-blue-600 text-white rounded px-2 py-1 disabled:opacity-50"
            >
              {isPending ? '…' : 'OK'}
            </button>
          </form>
        )}

        {enrollError && (
          <p className="text-xs text-red-600">{enrollError}</p>
        )}
      </div>
    </div>
  );
}
