import { useQuery } from '@tanstack/react-query';
import { authFetch, getSettings } from './client';
import type { SearchRequest, SearchResponse } from '../types/api';
import { formatISO } from 'date-fns';

export type SearchFilters = {
  personIds:           string[];
  classes:             string[];
  dateFrom:            Date | null;
  dateTo:              Date | null;
  videoIds:            string[];
  includeUnknownFaces: boolean;
  page:                number;
  pageSize:            number;
};

export async function searchFrames(filters: SearchFilters): Promise<SearchResponse> {
  // Convert empty arrays to undefined — API treats [] differently from null/missing:
  // empty array = "match nothing" vs absent field = "no filter applied"
  const body: SearchRequest = {
    person_ids:            filters.personIds.length  ? filters.personIds  : undefined,
    classes:               filters.classes.length    ? filters.classes    : undefined,
    video_ids:             filters.videoIds.length   ? filters.videoIds   : undefined,
    date_from:             filters.dateFrom ? formatISO(filters.dateFrom) : undefined,
    date_to:               filters.dateTo   ? formatISO(filters.dateTo, { representation: 'complete' }).replace('T00:00:00', 'T23:59:59') : undefined,
    include_unknown_faces: filters.includeUnknownFaces,
    page:                  filters.page,
    page_size:             filters.pageSize,
  };

  return authFetch('/search', {
    method: 'POST',
    body: JSON.stringify(body),
  }).then(r => r.json());
}

/** POST /search as a useQuery — filter state is the query key, changes trigger refetch. */
export function useSearch(filters: SearchFilters) {
  const { apiToken } = getSettings();
  return useQuery({
    queryKey:        ['search', filters],
    queryFn:         () => searchFrames(filters),
    staleTime:       60_000,
    placeholderData: (prev) => prev,  // keep previous results visible during refetch
    enabled:         !!apiToken,
  });
}
