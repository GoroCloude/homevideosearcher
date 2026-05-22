import { useState } from 'react';
import { format, parseISO } from 'date-fns';
import type { ClusterItem } from '../types/api';
import { useCreatePerson } from '../api/persons';
import { usePromoteCluster, useIgnoreCluster, useRestoreCluster, useLabelCluster } from '../api/clusters';
import FrameThumbnail from './FrameThumbnail';
import { addToast } from '../hooks/useToast';

interface Props {
  cluster:          ClusterItem;
  onEnrolled?:      () => void;   // called after successful enroll + promote
  showRestoreOnly?: boolean;      // true → only show Restore button (used in Ignored section)
  onRestored?:      () => void;   // called after successful restore
}

function fmtDate(iso: string | null): string {
  if (!iso) return '—';
  try { return format(parseISO(iso), 'MMM d, yyyy'); }
  catch { return iso; }
}

export default function ClusterCard({ cluster, onEnrolled, showRestoreOnly, onRestored }: Props) {
  const [enrolling,    setEnrolling]    = useState(false);
  const [personName,   setPersonName]   = useState('');
  const [enrollError,  setEnrollError]  = useState<string | null>(null);
  const [enrollDone,   setEnrollDone]   = useState(false);
  const [editingLabel, setEditingLabel] = useState(false);
  const [labelDraft,   setLabelDraft]   = useState(cluster.label ?? '');

  const createPerson   = useCreatePerson();
  const promoteCluster = usePromoteCluster();
  const ignoreCluster  = useIgnoreCluster();
  const restoreCluster = useRestoreCluster();
  const labelCluster   = useLabelCluster();

  async function handleEnroll(e: React.FormEvent) {
    e.preventDefault();
    const name = personName.trim();
    if (!name) return;

    setEnrollError(null);
    try {
      // Step 1: Create the person
      const person = await createPerson.mutateAsync(name);

      // Step 2: Promote cluster — links cluster embeddings to the new person
      // without triggering a full library rematch
      await promoteCluster.mutateAsync({ clusterId: cluster.id, personId: person.id });

      setEnrollDone(true);
      setEnrolling(false);
      onEnrolled?.();
    } catch (err) {
      setEnrollError(err instanceof Error ? err.message : 'Enroll failed');
    }
  }

  async function handleIgnore() {
    try {
      await ignoreCluster.mutateAsync(cluster.id);
    } catch {
      // silently swallow — cluster list will refresh regardless
    }
  }

  async function handleRestore() {
    try {
      await restoreCluster.mutateAsync(cluster.id);
      onRestored?.();
    } catch {
      // silently swallow
    }
  }

  async function handleLabelBlur() {
    const trimmed  = labelDraft.trim();
    const newLabel = trimmed || null;    // empty string → null (CLU-04: clear label)
    if (newLabel === cluster.label) {    // no-op if unchanged
      setEditingLabel(false);
      return;
    }
    try {
      await labelCluster.mutateAsync({ clusterId: cluster.id, label: newLabel });
      addToast('Label saved', 'success');
    } catch {
      addToast('Failed to save label', 'error');
    }
    setEditingLabel(false);
  }

  const isPending = createPerson.isPending || promoteCluster.isPending;

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

        {/* Inline label edit — CLU-01 (save), CLU-02 (display), CLU-04 (clear) */}
        <div className="mt-1">
          {editingLabel ? (
            <input
              type="text"
              value={labelDraft}
              onChange={e => setLabelDraft(e.target.value)}
              onBlur={handleLabelBlur}
              onKeyDown={e => { if (e.key === 'Enter') e.currentTarget.blur(); }}
              maxLength={100}
              autoFocus
              className="text-xs border border-gray-300 rounded px-2 py-1 focus:outline-none focus:ring-2 focus:ring-blue-500 w-full"
            />
          ) : cluster.label ? (
            <div
              className="flex items-center gap-1 cursor-pointer group"
              onClick={() => { setLabelDraft(cluster.label ?? ''); setEditingLabel(true); }}
            >
              <span className="text-xs text-gray-700 truncate">{cluster.label}</span>
              <span className="text-gray-400 group-hover:text-gray-600 text-xs">✏</span>
            </div>
          ) : (
            <div
              className="flex items-center gap-1 cursor-pointer opacity-0 group-hover:opacity-100"
              onClick={() => { setLabelDraft(''); setEditingLabel(true); }}
              aria-label="Edit label"
            >
              <span className="text-gray-400 text-xs">✏</span>
            </div>
          )}
        </div>

        {/* Actions */}
        {showRestoreOnly ? (
          <div className="mt-auto">
            <button
              onClick={handleRestore}
              disabled={restoreCluster.isPending}
              className="w-full text-xs font-medium text-gray-600 hover:text-gray-800 border border-gray-300 rounded px-2 py-1.5 transition-colors disabled:opacity-50"
            >
              {restoreCluster.isPending ? '…' : '↩ Restore'}
            </button>
          </div>
        ) : enrollDone ? (
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
              onClick={handleIgnore}
              disabled={ignoreCluster.isPending}
              title="Mark as noise — hide from active clusters"
              className="text-xs text-gray-500 hover:text-gray-700 border border-gray-200 hover:border-gray-400 rounded px-2 py-1.5 transition-colors disabled:opacity-50"
            >
              {ignoreCluster.isPending ? '…' : '🚫 Noise'}
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
