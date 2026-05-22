/**
 * RED tests for Task 1: ClusterItem.label field + patchClusterLabel fn + useLabelCluster hook
 *
 * These tests will FAIL before implementation (patchClusterLabel and useLabelCluster
 * are not yet exported from clusters.ts; ClusterItem does not yet have a label field).
 */
import { describe, it, expect, vi, beforeEach } from 'vitest';
import { renderHook, waitFor } from '@testing-library/react';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import React from 'react';

// ── Hoisted mocks ─────────────────────────────────────────────────────────────
const { mockAuthFetch } = vi.hoisted(() => ({
  mockAuthFetch: vi.fn(),
}));

vi.mock('../api/client', () => ({
  authFetch:   mockAuthFetch,
  getSettings: vi.fn(() => ({ apiToken: 'test-token', apiBaseUrl: '' })),
}));

// ── Imports under test (imported AFTER mock so mock is applied) ───────────────
import type { ClusterItem } from '../types/api';

// NOTE: These imports intentionally reference exports that do NOT yet exist.
// They will throw "is not a function" at call-time → RED state confirmed.
import { patchClusterLabel, useLabelCluster } from '../api/clusters';

// ── Helpers ───────────────────────────────────────────────────────────────────
function makeWrapper() {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return function Wrapper({ children }: { children: React.ReactNode }) {
    return React.createElement(QueryClientProvider, { client: qc }, children);
  };
}

// ── ClusterItem.label type contract ──────────────────────────────────────────
describe('ClusterItem.label', () => {
  it('accepts string label', () => {
    const item: ClusterItem = {
      id:                      'abc',
      representative_frame_id: null,
      appearance_count:        3,
      first_seen:              null,
      last_seen:               null,
      thumbnail_url:           null,
      ignored:                 false,
      label:                   'Grandma',
    };
    expect(item.label).toBe('Grandma');
  });

  it('accepts null label', () => {
    const item: ClusterItem = {
      id:                      'abc',
      representative_frame_id: null,
      appearance_count:        3,
      first_seen:              null,
      last_seen:               null,
      thumbnail_url:           null,
      ignored:                 false,
      label:                   null,
    };
    expect(item.label).toBeNull();
  });
});

// ── patchClusterLabel ─────────────────────────────────────────────────────────
describe('patchClusterLabel', () => {
  beforeEach(() => {
    mockAuthFetch.mockReset();
    mockAuthFetch.mockResolvedValue(new Response('{}', { status: 200 }));
  });

  it('calls PATCH /clusters/{id}/label with JSON body containing the label', async () => {
    await patchClusterLabel('cluster-123', 'Grandma');

    expect(mockAuthFetch).toHaveBeenCalledOnce();
    expect(mockAuthFetch).toHaveBeenCalledWith('/clusters/cluster-123/label', {
      method: 'PATCH',
      body:   JSON.stringify({ label: 'Grandma' }),
    });
  });

  it('sends null label to clear nickname', async () => {
    await patchClusterLabel('cluster-456', null);

    expect(mockAuthFetch).toHaveBeenCalledWith('/clusters/cluster-456/label', {
      method: 'PATCH',
      body:   JSON.stringify({ label: null }),
    });
  });

  it('returns void (Promise<void>)', async () => {
    const result = await patchClusterLabel('id', 'label');
    expect(result).toBeUndefined();
  });
});

// ── useLabelCluster ───────────────────────────────────────────────────────────
describe('useLabelCluster', () => {
  beforeEach(() => {
    mockAuthFetch.mockReset();
    mockAuthFetch.mockResolvedValue(new Response('{}', { status: 200 }));
  });

  it('is exported as a function', () => {
    expect(typeof useLabelCluster).toBe('function');
  });

  it('returns a mutation object with mutate + mutateAsync', () => {
    const wrapper = makeWrapper();
    const { result } = renderHook(() => useLabelCluster(), { wrapper });
    expect(typeof result.current.mutate).toBe('function');
    expect(typeof result.current.mutateAsync).toBe('function');
  });

  it('calls patchClusterLabel via mutateAsync and invalidates [clusters]', async () => {
    const wrapper = makeWrapper();
    const { result } = renderHook(() => useLabelCluster(), { wrapper });

    await result.current.mutateAsync({ clusterId: 'c-1', label: 'Uncle Bob' });

    await waitFor(() => expect(result.current.isSuccess).toBe(true));

    expect(mockAuthFetch).toHaveBeenCalledWith('/clusters/c-1/label', {
      method: 'PATCH',
      body:   JSON.stringify({ label: 'Uncle Bob' }),
    });
  });
});
