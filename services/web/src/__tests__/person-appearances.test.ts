/**
 * RED tests for Task 1: getPersonAppearances raw fn + usePersonAppearances hook
 *
 * These tests will FAIL before implementation because getPersonAppearances
 * and usePersonAppearances are not yet exported from api/persons.ts.
 */
import { describe, it, expect, vi, beforeEach } from 'vitest';
import { renderHook, waitFor } from '@testing-library/react';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import React from 'react';

// ── Hoisted mocks ─────────────────────────────────────────────────────────────
const { mockAuthFetch, mockGetSettings } = vi.hoisted(() => ({
  mockAuthFetch:   vi.fn(),
  mockGetSettings: vi.fn(),
}));

vi.mock('../api/client', () => ({
  authFetch:   mockAuthFetch,
  getSettings: mockGetSettings,
}));

// ── Imports under test (imported AFTER mock so mock is applied) ───────────────
// NOTE: These imports intentionally reference exports that do NOT yet exist.
// They will throw "is not a function" at call-time → RED state confirmed.
import { getPersonAppearances, usePersonAppearances } from '../api/persons';
import type { PersonAppearancesResponse } from '../types/api';

// ── Helpers ───────────────────────────────────────────────────────────────────
function makeWrapper() {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return function Wrapper({ children }: { children: React.ReactNode }) {
    return React.createElement(QueryClientProvider, { client: qc }, children);
  };
}

const MOCK_RESPONSE: PersonAppearancesResponse = {
  person_id:   'aaaaaaaa-0000-0000-0000-000000000001',
  person_name: 'Alice',
  results: [
    {
      video_id:         'bbbbbbbb-0000-0000-0000-000000000001',
      video_minio_key:  'videos/test.mp4',
      recorded_at:      '2024-03-15T10:00:00Z',
      duration_sec:     120,
      first_ts_ms:      5000,
      appearance_count: 3,
      thumbnail_url:    'https://minio.example.com/frames/test.jpg?sig=xxx',
    },
  ],
};

// ── getPersonAppearances ──────────────────────────────────────────────────────
describe('getPersonAppearances', () => {
  beforeEach(() => {
    mockAuthFetch.mockReset();
    mockGetSettings.mockReset();
    mockGetSettings.mockReturnValue({ apiToken: 'test-token', apiBaseUrl: '' });
  });

  it('calls authFetch with /persons/{id}/appearances URL', async () => {
    mockAuthFetch.mockResolvedValue({
      json: vi.fn().mockResolvedValue(MOCK_RESPONSE),
    });

    await getPersonAppearances('aaaaaaaa-0000-0000-0000-000000000001');

    expect(mockAuthFetch).toHaveBeenCalledOnce();
    expect(mockAuthFetch).toHaveBeenCalledWith(
      '/persons/aaaaaaaa-0000-0000-0000-000000000001/appearances',
    );
  });

  it('returns parsed PersonAppearancesResponse', async () => {
    mockAuthFetch.mockResolvedValue({
      json: vi.fn().mockResolvedValue(MOCK_RESPONSE),
    });

    const result = await getPersonAppearances('aaaaaaaa-0000-0000-0000-000000000001');

    expect(result.person_id).toBe('aaaaaaaa-0000-0000-0000-000000000001');
    expect(result.person_name).toBe('Alice');
    expect(result.results).toHaveLength(1);
    expect(result.results[0].first_ts_ms).toBe(5000);
  });
});

// ── usePersonAppearances ──────────────────────────────────────────────────────
describe('usePersonAppearances', () => {
  beforeEach(() => {
    mockAuthFetch.mockReset();
    mockGetSettings.mockReset();
  });

  it('is exported as a function', () => {
    expect(typeof usePersonAppearances).toBe('function');
  });

  it('does NOT fire when personId is empty string (enabled: false)', () => {
    mockGetSettings.mockReturnValue({ apiToken: 'test-token', apiBaseUrl: '' });
    const wrapper = makeWrapper();
    const { result } = renderHook(() => usePersonAppearances(''), { wrapper });
    // Should not be loading — query is disabled
    expect(result.current.fetchStatus).toBe('idle');
    expect(mockAuthFetch).not.toHaveBeenCalled();
  });

  it('does NOT fire when apiToken is absent (enabled: false)', () => {
    mockGetSettings.mockReturnValue({ apiToken: '', apiBaseUrl: '' });
    const wrapper = makeWrapper();
    const { result } = renderHook(
      () => usePersonAppearances('aaaaaaaa-0000-0000-0000-000000000001'),
      { wrapper },
    );
    expect(result.current.fetchStatus).toBe('idle');
    expect(mockAuthFetch).not.toHaveBeenCalled();
  });

  it('fires with queryKey [person-appearances, personId] when token + personId both set', async () => {
    mockGetSettings.mockReturnValue({ apiToken: 'test-token', apiBaseUrl: '' });
    mockAuthFetch.mockResolvedValue({
      json: vi.fn().mockResolvedValue(MOCK_RESPONSE),
    });

    const wrapper = makeWrapper();
    const { result } = renderHook(
      () => usePersonAppearances('aaaaaaaa-0000-0000-0000-000000000001'),
      { wrapper },
    );

    await waitFor(() => expect(result.current.isSuccess).toBe(true));

    expect(mockAuthFetch).toHaveBeenCalledWith(
      '/persons/aaaaaaaa-0000-0000-0000-000000000001/appearances',
    );
    expect(result.current.data?.person_name).toBe('Alice');
  });
});
