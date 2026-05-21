import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query';
import { authFetch, getSettings } from './client';
import type { ClusterItem } from '../types/api';

// ── Raw API functions ──────────────────────────────────────────────────────────

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

export async function listIgnoredClusters(): Promise<ClusterItem[]> {
  try {
    return await authFetch('/clusters?include_ignored=true').then(r => r.json());
  } catch (err) {
    if (err instanceof Error && (err.message.startsWith('404') || err.message.startsWith('422'))) {
      return [];
    }
    throw err;
  }
}

export async function promoteCluster(clusterId: string, personId: string): Promise<void> {
  await authFetch(`/clusters/${clusterId}/promote?person_id=${personId}`, { method: 'POST' });
}

export async function ignoreCluster(clusterId: string): Promise<void> {
  await authFetch(`/clusters/${clusterId}/ignore`, { method: 'POST' });
}

export async function restoreCluster(clusterId: string): Promise<void> {
  await authFetch(`/clusters/${clusterId}/ignore`, { method: 'DELETE' });
}

// ── TanStack Query hooks (v5 object-form only) ─────────────────────────────────

export function useClusters() {
  const { apiToken } = getSettings();
  return useQuery({
    queryKey: ['clusters'],
    queryFn:  listClusters,
    staleTime: 60_000,
    enabled:   !!apiToken,
  });
}

export function useIgnoredClusters() {
  const { apiToken } = getSettings();
  return useQuery({
    queryKey: ['clusters', 'ignored'],
    queryFn:  listIgnoredClusters,
    staleTime: 60_000,
    enabled:   !!apiToken,
  });
}

export function usePromoteCluster() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: ({ clusterId, personId }: { clusterId: string; personId: string }) =>
      promoteCluster(clusterId, personId),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ['clusters'] });
      qc.invalidateQueries({ queryKey: ['clusters', 'ignored'] });
      qc.invalidateQueries({ queryKey: ['persons'] });
    },
  });
}

export function useIgnoreCluster() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (clusterId: string) => ignoreCluster(clusterId),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ['clusters'] });
      qc.invalidateQueries({ queryKey: ['clusters', 'ignored'] });
    },
  });
}

export function useRestoreCluster() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (clusterId: string) => restoreCluster(clusterId),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ['clusters'] });
      qc.invalidateQueries({ queryKey: ['clusters', 'ignored'] });
    },
  });
}
