import { useState, useCallback } from 'react';
import { Link } from 'react-router-dom';
import clsx from 'clsx';
import { useSearch, type SearchFilters } from '../api/search';
import { usePersons } from '../api/persons';
import { useSettings } from '../context/SettingsContext';
import FrameThumbnail from '../components/FrameThumbnail';
import VideoModal     from '../components/VideoModal';
import type { FrameResult } from '../types/api';

const DEFAULT_FILTERS: SearchFilters = {
  personIds:           [],
  classes:             [],
  dateFrom:            null,
  dateTo:              null,
  videoIds:            [],
  includeUnknownFaces: false,
  page:                1,
  pageSize:            20,
};

const AVAILABLE_CLASSES = [
  'person', 'car', 'dog', 'cat', 'bicycle', 'motorcycle', 'bus', 'truck', 'bird',
];

export default function SearchPage() {
  const { settings } = useSettings();
  const [pendingFilters, setPendingFilters] = useState<SearchFilters>(DEFAULT_FILTERS);
  const [appliedFilters, setAppliedFilters] = useState<SearchFilters>(DEFAULT_FILTERS);
  const [selectedFrame, setSelectedFrame]   = useState<FrameResult | null>(null);
  const [sidebarOpen,   setSidebarOpen]     = useState(false);

  const { data, isLoading, isFetching } = useSearch(appliedFilters);
  const { data: persons = [] } = usePersons();

  const handleApply = useCallback(() => {
    setAppliedFilters({ ...pendingFilters, page: 1 });
    setSidebarOpen(false);
  }, [pendingFilters]);

  const handleClear = useCallback(() => {
    setPendingFilters(DEFAULT_FILTERS);
    setAppliedFilters(DEFAULT_FILTERS);
  }, []);

  const handlePageChange = (newPage: number) => {
    setAppliedFilters(prev => ({ ...prev, page: newPage }));
  };

  const toggleClass = (cls: string) => {
    setPendingFilters(prev => ({
      ...prev,
      classes: prev.classes.includes(cls)
        ? prev.classes.filter(c => c !== cls)
        : [...prev.classes, cls],
    }));
  };

  const togglePerson = (id: string) => {
    setPendingFilters(prev => ({
      ...prev,
      personIds: prev.personIds.includes(id)
        ? prev.personIds.filter(p => p !== id)
        : [...prev.personIds, id],
    }));
  };

  // No-token banner
  if (!settings.apiToken) {
    return (
      <div className="p-6">
        <div className="bg-amber-50 border border-amber-200 rounded-lg p-4 flex items-center gap-3">
          <span className="text-amber-600">⚠</span>
          <span className="text-sm text-amber-800">
            API token not configured.{' '}
            <Link to="/settings" className="font-medium underline hover:no-underline">
              Go to Settings →
            </Link>
          </span>
        </div>
      </div>
    );
  }

  const pagination = data?.pagination;
  const results    = data?.results ?? [];
  const totalPages = pagination ? Math.ceil(pagination.total / pagination.page_size) : 0;

  // Filter sidebar content (shared between desktop sidebar and mobile drawer)
  const filterContent = (
    <div className="space-y-6">
      {/* Persons */}
      {persons.length > 0 && (
        <div>
          <h3 className="text-xs font-semibold uppercase tracking-wide text-gray-500 mb-2">
            People
          </h3>
          <div className="space-y-1">
            {persons.map(p => (
              <label key={p.id} className="flex items-center gap-2 text-sm cursor-pointer">
                <input
                  type="checkbox"
                  checked={pendingFilters.personIds.includes(p.id)}
                  onChange={() => togglePerson(p.id)}
                  className="rounded text-blue-600"
                />
                <span className="text-gray-700">{p.name}</span>
              </label>
            ))}
          </div>
        </div>
      )}

      {/* Classes */}
      <div>
        <h3 className="text-xs font-semibold uppercase tracking-wide text-gray-500 mb-2">
          Object Classes
        </h3>
        <div className="space-y-1">
          {AVAILABLE_CLASSES.map(cls => (
            <label key={cls} className="flex items-center gap-2 text-sm cursor-pointer capitalize">
              <input
                type="checkbox"
                checked={pendingFilters.classes.includes(cls)}
                onChange={() => toggleClass(cls)}
                className="rounded text-blue-600"
              />
              <span className="text-gray-700">{cls}</span>
            </label>
          ))}
        </div>
      </div>

      {/* Date range */}
      <div>
        <h3 className="text-xs font-semibold uppercase tracking-wide text-gray-500 mb-2">
          Date Range
        </h3>
        <div className="space-y-2">
          <div>
            <label className="text-xs text-gray-500 mb-1 block">From</label>
            <input
              type="date"
              value={pendingFilters.dateFrom ? pendingFilters.dateFrom.toISOString().split('T')[0] : ''}
              onChange={e => setPendingFilters(prev => ({
                ...prev,
                dateFrom: e.target.value ? new Date(e.target.value) : null,
              }))}
              className="w-full text-sm border border-gray-300 rounded px-2 py-1.5 focus:outline-none focus:ring-2 focus:ring-blue-500"
            />
          </div>
          <div>
            <label className="text-xs text-gray-500 mb-1 block">To</label>
            <input
              type="date"
              value={pendingFilters.dateTo ? pendingFilters.dateTo.toISOString().split('T')[0] : ''}
              onChange={e => setPendingFilters(prev => ({
                ...prev,
                dateTo: e.target.value ? new Date(e.target.value) : null,
              }))}
              className="w-full text-sm border border-gray-300 rounded px-2 py-1.5 focus:outline-none focus:ring-2 focus:ring-blue-500"
            />
          </div>
        </div>
      </div>

      {/* Include unknowns */}
      <div>
        <label className="flex items-center gap-2 text-sm cursor-pointer">
          <input
            type="checkbox"
            checked={pendingFilters.includeUnknownFaces}
            onChange={e => setPendingFilters(prev => ({
              ...prev,
              includeUnknownFaces: e.target.checked,
            }))}
            className="rounded text-blue-600"
          />
          <span className="text-gray-700">Include unknown faces</span>
        </label>
      </div>

      {/* Actions */}
      <div className="flex gap-3 pt-1">
        <button
          onClick={handleApply}
          className="flex-1 bg-blue-600 text-white text-sm font-medium py-2 rounded-lg hover:bg-blue-700 transition-colors"
        >
          Apply Filters
        </button>
        <button
          onClick={handleClear}
          className="text-sm text-gray-500 hover:text-gray-700 underline"
        >
          Clear
        </button>
      </div>
    </div>
  );

  return (
    <div className="flex h-full">

      {/* Desktop filter sidebar */}
      <aside className="hidden md:block w-64 bg-white border-r border-gray-200 p-4 overflow-y-auto shrink-0">
        <h2 className="text-sm font-semibold text-gray-800 mb-4">Filters</h2>
        {filterContent}
      </aside>

      {/* Mobile filter drawer overlay */}
      {sidebarOpen && (
        <div className="md:hidden fixed inset-0 z-40 flex">
          <div
            className="absolute inset-0 bg-black/40"
            onClick={() => setSidebarOpen(false)}
          />
          <div className="relative bg-white w-72 h-full overflow-y-auto p-4 shadow-xl">
            <div className="flex items-center justify-between mb-4">
              <h2 className="text-sm font-semibold text-gray-800">Filters</h2>
              <button
                onClick={() => setSidebarOpen(false)}
                className="text-gray-400 hover:text-gray-600 text-xl"
                aria-label="Close filters"
              >×</button>
            </div>
            {filterContent}
          </div>
        </div>
      )}

      {/* Main content */}
      <div className="flex-1 overflow-y-auto">

        {/* Mobile filter toggle button */}
        <div className="md:hidden flex items-center justify-between px-4 pt-4 pb-2 border-b border-gray-100">
          <button
            onClick={() => setSidebarOpen(true)}
            className="inline-flex items-center gap-2 text-sm font-medium text-gray-700 border border-gray-300 rounded-lg px-3 py-1.5 hover:bg-gray-50"
          >
            🎛 Filters
            {(appliedFilters.personIds.length + appliedFilters.classes.length > 0) && (
              <span className="bg-blue-600 text-white text-xs rounded-full w-4 h-4 flex items-center justify-center">
                {appliedFilters.personIds.length + appliedFilters.classes.length}
              </span>
            )}
          </button>
          {isFetching && !isLoading && (
            <span className="text-xs text-gray-400 animate-pulse">Refreshing…</span>
          )}
        </div>

        <div className="p-4">
          {/* Loading skeletons */}
          {isLoading && (
            <div className="grid grid-cols-1 sm:grid-cols-2 md:grid-cols-3 xl:grid-cols-4 gap-3">
              {Array.from({ length: 12 }).map((_, i) => (
                <div key={i} className="aspect-video bg-gray-200 rounded animate-pulse" />
              ))}
            </div>
          )}

          {/* Empty state */}
          {!isLoading && results.length === 0 && (
            <div className="flex flex-col items-center justify-center py-20 text-gray-400">
              <span className="text-4xl mb-3">🔍</span>
              <p className="text-sm">No results — try different filters</p>
            </div>
          )}

          {/* Results grid */}
          {results.length > 0 && (
            <>
              <div className="grid grid-cols-1 sm:grid-cols-2 md:grid-cols-3 xl:grid-cols-4 gap-3">
                {results.map(frame => (
                  <FrameThumbnail
                    key={frame.frame_id}
                    frameId={frame.frame_id}
                    alt={`Frame at ${(frame.ts_ms / 1000).toFixed(1)}s`}
                    className={clsx(
                      'aspect-video cursor-pointer hover:ring-2 hover:ring-blue-400 transition-all rounded'
                    )}
                    onClick={() => setSelectedFrame(frame)}
                  />
                ))}
              </div>

              {/* Pagination */}
              {pagination && totalPages > 1 && (
                <div className="flex items-center justify-center gap-2 mt-6 flex-wrap">
                  <button
                    onClick={() => handlePageChange(pagination.page - 1)}
                    disabled={pagination.page <= 1}
                    className="px-3 py-1.5 text-sm border rounded disabled:opacity-40 hover:bg-gray-50"
                  >
                    ← Prev
                  </button>

                  {Array.from({ length: Math.min(totalPages, 7) }, (_, i) => {
                    const p = i + 1;
                    return (
                      <button
                        key={p}
                        onClick={() => handlePageChange(p)}
                        className={clsx(
                          'px-3 py-1.5 text-sm border rounded transition-colors',
                          pagination.page === p
                            ? 'bg-blue-600 text-white border-blue-600'
                            : 'hover:bg-gray-50',
                        )}
                      >
                        {p}
                      </button>
                    );
                  })}

                  {totalPages > 7 && pagination.page < totalPages - 3 && (
                    <span className="text-gray-400 text-sm">…{totalPages}</span>
                  )}

                  <button
                    onClick={() => handlePageChange(pagination.page + 1)}
                    disabled={!pagination.has_next}
                    className="px-3 py-1.5 text-sm border rounded disabled:opacity-40 hover:bg-gray-50"
                  >
                    Next →
                  </button>

                  <span className="text-xs text-gray-400 w-full text-center sm:w-auto sm:text-left">
                    Page {pagination.page} of {totalPages} · {pagination.total} results
                  </span>
                </div>
              )}
            </>
          )}
        </div>
      </div>

      {/* Frame detail modal */}
      <VideoModal frame={selectedFrame} onClose={() => setSelectedFrame(null)} />
    </div>
  );
}
