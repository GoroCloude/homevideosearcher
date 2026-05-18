import { useQuery } from '@tanstack/react-query';
import { authFetch, getSettings } from './client';
import type { ClusterItem } from '../types/api';

export async function listClusters(): Promise<ClusterItem[]> {
  try {
    return await authFetch('/clusters').then(r => r.json());
  } catch (err) {
    // Phase 3 GET /clusters endpoint not yet built — return empty list gracefully.
    // A 404 or 422 means the endpoint doesn't exist; other errors are re-thrown.
    if (err instanceof Error && (err.message.startsWith('404') || err.message.startsWith('422'))) {
      return [];
    }
    throw err;
  }
}

export function useClusters() {
  const { apiToken } = getSettings();
  return useQuery({
    queryKey: ['clusters'],
    queryFn:  listClusters,
    staleTime: 60_000,
    enabled:   !!apiToken,
  });
}
