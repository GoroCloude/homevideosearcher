import { useNavigate, useParams, Link } from 'react-router-dom';
import { format, parseISO } from 'date-fns';
import { usePersonAppearances } from '../api/persons';
import { useSettings } from '../context/SettingsContext';
import type { VideoAppearance } from '../types/api';

// ── Formatting helpers ────────────────────────────────────────────────────────

function fmtDate(iso: string | null): string {
  if (!iso) return '—';
  try { return format(parseISO(iso), 'MMM d, yyyy'); }
  catch { return iso; }
}

function fmtSeconds(ms: number): string {
  return `${(ms / 1000).toFixed(1)}s`;
}

function monthKey(iso: string | null): string {
  if (!iso) return '';   // empty string → "Unknown Date" group
  try { return format(parseISO(iso), 'MMMM yyyy'); }
  catch { return ''; }
}

// ── Timeline grouping ─────────────────────────────────────────────────────────

function groupByMonth(appearances: VideoAppearance[]): Array<{ month: string; items: VideoAppearance[] }> {
  // Sort chronologically (oldest first) for the timeline section.
  const sorted = [...appearances].sort((a, b) => {
    const aDate = a.recorded_at ?? '';
    const bDate = b.recorded_at ?? '';
    return aDate.localeCompare(bDate);
  });

  const map = new Map<string, VideoAppearance[]>();
  const dated: string[]   = [];  // ordered month keys for dated groups
  const undated: VideoAppearance[] = [];

  for (const item of sorted) {
    const key = monthKey(item.recorded_at);
    if (!key) {
      undated.push(item);
      continue;
    }
    if (!map.has(key)) {
      map.set(key, []);
      dated.push(key);
    }
    map.get(key)!.push(item);
  }

  const groups = dated.map(month => ({ month, items: map.get(month)! }));
  if (undated.length > 0) {
    groups.push({ month: 'Unknown Date', items: undated });
  }
  return groups;
}

// ── Page component ────────────────────────────────────────────────────────────

export default function PersonAppearancePage() {
  const { id }   = useParams<{ id: string }>();
  const navigate = useNavigate();

  const { settings } = useSettings();
  const { data, isLoading, isError, error } = usePersonAppearances(id ?? '');

  // ── No-token guard ─────────────────────────────────────────────────────────
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

  // ── Loading ────────────────────────────────────────────────────────────────
  if (isLoading) {
    return (
      <div className="p-6 space-y-4">
        <div className="h-6 w-48 bg-gray-200 rounded animate-pulse" />
        <div className="h-56 bg-gray-200 rounded animate-pulse" />
        <div className="h-40 bg-gray-200 rounded animate-pulse" />
      </div>
    );
  }

  // ── Error / not found ──────────────────────────────────────────────────────
  if (isError || !data) {
    return (
      <div className="p-6">
        <div className="bg-red-50 border border-red-200 rounded-lg p-4 text-sm text-red-700">
          {error instanceof Error ? error.message : 'Person not found'}
        </div>
        <button
          onClick={() => navigate('/people')}
          className="mt-4 text-sm text-blue-600 hover:underline"
        >
          ← Back to People
        </button>
      </div>
    );
  }

  const appearances  = data.results;
  const totalCount   = appearances.reduce((sum, a) => sum + a.appearance_count, 0);
  const datedItems   = appearances.filter(a => a.recorded_at != null);
  const dateRange    = datedItems.length >= 2
    ? `${fmtDate(datedItems[datedItems.length - 1].recorded_at)} – ${fmtDate(datedItems[0].recorded_at)}`
    : datedItems.length === 1
      ? fmtDate(datedItems[0].recorded_at)
      : null;

  const timelineGroups = groupByMonth(appearances);

  // ── Page ───────────────────────────────────────────────────────────────────
  return (
    <div className="p-4 md:p-6 max-w-4xl mx-auto space-y-6">

      {/* Back link */}
      <button
        onClick={() => navigate('/people')}
        className="text-sm text-blue-600 hover:underline"
      >
        ← Back to People
      </button>

      {/* Person header */}
      <div className="bg-white border border-gray-200 rounded-xl p-5 shadow-sm">
        <div className="flex items-center gap-3 mb-3">
          <div className="text-3xl select-none">👤</div>
          <h1 className="text-xl font-semibold text-gray-900">{data.person_name}</h1>
        </div>
        <dl className="grid grid-cols-2 sm:grid-cols-3 gap-x-6 gap-y-2 text-sm">
          <div>
            <dt className="text-xs uppercase tracking-wide text-gray-400 mb-0.5">Videos</dt>
            <dd className="text-gray-800">{appearances.length}</dd>
          </div>
          <div>
            <dt className="text-xs uppercase tracking-wide text-gray-400 mb-0.5">Total Appearances</dt>
            <dd className="text-gray-800">{totalCount}</dd>
          </div>
          {dateRange && (
            <div>
              <dt className="text-xs uppercase tracking-wide text-gray-400 mb-0.5">Date Range</dt>
              <dd className="text-gray-800">{dateRange}</dd>
            </div>
          )}
        </dl>
      </div>

      {/* ── Video appearances list ─────────────────────────────────────────── */}
      <div>
        <h2 className="text-sm font-semibold text-gray-700 mb-3">
          Videos ({appearances.length})
        </h2>

        {appearances.length === 0 ? (
          <div className="flex flex-col items-center py-16 text-gray-400">
            <span className="text-4xl mb-3">🎞️</span>
            <p className="text-sm">No appearances found</p>
            <p className="text-xs mt-1">{data.person_name} has not been matched in any video yet</p>
          </div>
        ) : (
          <div className="space-y-2">
            {appearances.map(a => (
              <button
                key={a.video_id}
                onClick={() => navigate(`/videos/${a.video_id}?t=${a.first_ts_ms}`)}
                className="w-full flex items-center gap-4 bg-white border border-gray-200 rounded-xl p-3 shadow-sm hover:border-blue-300 hover:shadow-md transition-all text-left"
              >
                {/* Face thumbnail */}
                <div className="flex-none w-12 h-12 rounded-lg overflow-hidden bg-gray-100">
                  <img
                    src={a.thumbnail_url}
                    alt={`${data.person_name} in video`}
                    loading="lazy"
                    className="w-full h-full object-cover"
                  />
                </div>

                {/* Video info */}
                <div className="flex-1 min-w-0">
                  <p className="text-sm font-medium text-gray-900 truncate">
                    {fmtDate(a.recorded_at)}
                  </p>
                  <p className="text-xs text-gray-500 mt-0.5">
                    First at {fmtSeconds(a.first_ts_ms)}
                  </p>
                </div>

                {/* Appearance count badge */}
                <div className="flex-none">
                  <span className="inline-flex items-center rounded-full bg-blue-50 px-2.5 py-0.5 text-xs font-medium text-blue-700 border border-blue-100">
                    {a.appearance_count} {a.appearance_count === 1 ? 'appearance' : 'appearances'}
                  </span>
                </div>

                {/* Chevron */}
                <div className="flex-none text-gray-400 text-sm">›</div>
              </button>
            ))}
          </div>
        )}
      </div>

      {/* ── Appearance Timeline ────────────────────────────────────────────── */}
      {timelineGroups.length > 0 && (
        <div>
          <h2 className="text-sm font-semibold text-gray-700 mb-3">Appearance Timeline</h2>
          <div className="space-y-4">
            {timelineGroups.map(group => (
              <div key={group.month}>
                {/* Sticky month header */}
                <div className="sticky top-0 z-10 bg-gray-50 border border-gray-200 rounded-lg px-3 py-1.5 mb-2 flex items-center justify-between">
                  <span className="text-xs font-semibold text-gray-600 uppercase tracking-wide">
                    {group.month}
                  </span>
                  <span className="text-xs text-gray-400">
                    {group.items.length} {group.items.length === 1 ? 'video' : 'videos'}
                  </span>
                </div>

                {/* Appearances in this month */}
                <div className="space-y-1 pl-2">
                  {group.items.map(a => (
                    <button
                      key={a.video_id}
                      onClick={() => navigate(`/videos/${a.video_id}?t=${a.first_ts_ms}`)}
                      className="w-full flex items-center gap-3 px-3 py-2 rounded-lg hover:bg-gray-100 transition-colors text-left"
                    >
                      <span className="text-xs text-gray-700 flex-1 truncate">
                        {fmtDate(a.recorded_at)}
                      </span>
                      <span className="text-xs text-gray-400 flex-none">
                        {fmtSeconds(a.first_ts_ms)} · {a.appearance_count}×
                      </span>
                      <span className="text-gray-400 text-xs flex-none">›</span>
                    </button>
                  ))}
                </div>
              </div>
            ))}
          </div>
        </div>
      )}

    </div>
  );
}
