/**
 * RED tests for Task 2: PersonAppearancePage component
 *
 * These tests will FAIL before implementation because
 * PersonAppearancePage.tsx does not yet exist.
 */
import { describe, it, expect, vi, beforeEach } from 'vitest';
import { render, screen, fireEvent } from '@testing-library/react';
import { MemoryRouter, Route, Routes } from 'react-router-dom';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import React from 'react';

// ── Hoisted mocks ─────────────────────────────────────────────────────────────
const { mockUsePersonAppearances, mockUseSettings, mockNavigate } = vi.hoisted(() => ({
  mockUsePersonAppearances: vi.fn(),
  mockUseSettings:          vi.fn(),
  mockNavigate:             vi.fn(),
}));

vi.mock('../api/persons', async (importOriginal) => {
  const actual = await importOriginal<typeof import('../api/persons')>();
  return {
    ...actual,
    usePersonAppearances: mockUsePersonAppearances,
  };
});

vi.mock('../context/SettingsContext', () => ({
  useSettings: mockUseSettings,
}));

vi.mock('react-router-dom', async (importOriginal) => {
  const actual = await importOriginal<typeof import('react-router-dom')>();
  return {
    ...actual,
    useNavigate: () => mockNavigate,
  };
});

// ── Import under test ─────────────────────────────────────────────────────────
import PersonAppearancePage from '../pages/PersonAppearancePage';
import type { PersonAppearancesResponse } from '../types/api';

// ── Helpers ───────────────────────────────────────────────────────────────────
function makeWrapper(personId = 'person-123') {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return function Wrapper({ children }: { children: React.ReactNode }) {
    return React.createElement(
      QueryClientProvider,
      { client: qc },
      React.createElement(
        MemoryRouter,
        { initialEntries: [`/people/${personId}`] },
        React.createElement(
          Routes,
          null,
          React.createElement(Route, { path: '/people/:id', element: children }),
        ),
      ),
    );
  };
}

function renderPage(personId = 'person-123') {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    React.createElement(
      QueryClientProvider,
      { client: qc },
      React.createElement(
        MemoryRouter,
        { initialEntries: [`/people/${personId}`] },
        React.createElement(
          Routes,
          null,
          React.createElement(Route, {
            path: '/people/:id',
            element: React.createElement(PersonAppearancePage),
          }),
        ),
      ),
    ),
  );
}

const MOCK_DATA: PersonAppearancesResponse = {
  person_id:   'person-123',
  person_name: 'Alice',
  results: [
    {
      video_id:         'video-001',
      video_minio_key:  'videos/a.mp4',
      recorded_at:      '2024-03-15T10:00:00Z',
      duration_sec:     120,
      first_ts_ms:      5000,
      appearance_count: 3,
      thumbnail_url:    'https://minio.example.com/frames/thumb.jpg?sig=abc',
    },
    {
      video_id:         'video-002',
      video_minio_key:  'videos/b.mp4',
      recorded_at:      '2024-01-10T08:00:00Z',
      duration_sec:     60,
      first_ts_ms:      2000,
      appearance_count: 1,
      thumbnail_url:    'https://minio.example.com/frames/thumb2.jpg?sig=def',
    },
  ],
};

// ── Tests ─────────────────────────────────────────────────────────────────────

describe('PersonAppearancePage — no-token guard', () => {
  it('renders amber banner with Settings link when apiToken is absent', () => {
    mockUseSettings.mockReturnValue({ settings: { apiToken: '' } });
    mockUsePersonAppearances.mockReturnValue({ data: undefined, isLoading: false, isError: false });

    renderPage();

    expect(screen.getByText(/API token not configured/i)).toBeTruthy();
    expect(screen.getByText(/Go to Settings/i)).toBeTruthy();
  });
});

describe('PersonAppearancePage — loading state', () => {
  beforeEach(() => {
    mockUseSettings.mockReturnValue({ settings: { apiToken: 'tok' } });
  });

  it('renders loading skeleton while isLoading is true', () => {
    mockUsePersonAppearances.mockReturnValue({ data: undefined, isLoading: true, isError: false });

    const { container } = renderPage();

    // Three skeleton divs with animate-pulse
    const skeletons = container.querySelectorAll('.animate-pulse');
    expect(skeletons.length).toBeGreaterThanOrEqual(3);
  });
});

describe('PersonAppearancePage — error state', () => {
  beforeEach(() => {
    mockUseSettings.mockReturnValue({ settings: { apiToken: 'tok' } });
  });

  it('renders red error banner when isError is true', () => {
    mockUsePersonAppearances.mockReturnValue({
      data: undefined,
      isLoading: false,
      isError: true,
      error: new Error('Person not found'),
    });

    renderPage();

    expect(screen.getByText(/Person not found/i)).toBeTruthy();
  });

  it('renders "← Back to People" button that calls navigate(/people)', () => {
    mockNavigate.mockReset();
    mockUsePersonAppearances.mockReturnValue({
      data: undefined,
      isLoading: false,
      isError: true,
      error: new Error('Not found'),
    });

    renderPage();

    const backBtn = screen.getByText(/← Back to People/i);
    fireEvent.click(backBtn);
    expect(mockNavigate).toHaveBeenCalledWith('/people');
  });
});

describe('PersonAppearancePage — data loaded', () => {
  beforeEach(() => {
    mockUseSettings.mockReturnValue({ settings: { apiToken: 'tok' } });
    mockUsePersonAppearances.mockReturnValue({
      data: MOCK_DATA,
      isLoading: false,
      isError: false,
    });
  });

  it('renders the person name in the header', () => {
    renderPage();
    expect(screen.getByText('Alice')).toBeTruthy();
  });

  it('renders video count and total appearances', () => {
    renderPage();
    // Header stats — 2 videos, 3+1=4 total appearances
    expect(screen.getByText('2')).toBeTruthy();
    expect(screen.getByText('4')).toBeTruthy();
  });

  it('renders appearance count badges for each video row', () => {
    renderPage();
    expect(screen.getByText(/3 appearances/i)).toBeTruthy();
    expect(screen.getByText(/1 appearance/i)).toBeTruthy();
  });

  it('clicking a video row calls navigate with /videos/{id}?t={first_ts_ms}', () => {
    mockNavigate.mockReset();
    renderPage();

    // First video row (video-001, first_ts_ms=5000)
    const rows = screen.getAllByText(/Mar 15, 2024/i);
    // Click the parent button of the first match
    const rowBtn = rows[0].closest('button');
    expect(rowBtn).toBeTruthy();
    fireEvent.click(rowBtn!);

    expect(mockNavigate).toHaveBeenCalledWith('/videos/video-001?t=5000');
  });
});

describe('PersonAppearancePage — empty state', () => {
  beforeEach(() => {
    mockUseSettings.mockReturnValue({ settings: { apiToken: 'tok' } });
  });

  it('renders empty state when data.results is empty', () => {
    mockUsePersonAppearances.mockReturnValue({
      data: { ...MOCK_DATA, results: [] },
      isLoading: false,
      isError: false,
    });

    renderPage();

    expect(screen.getByText(/No appearances found/i)).toBeTruthy();
    // Should NOT show an error banner
    expect(screen.queryByText(/Person not found/i)).toBeNull();
  });
});

describe('PersonAppearancePage — timeline grouping', () => {
  beforeEach(() => {
    mockUseSettings.mockReturnValue({ settings: { apiToken: 'tok' } });
    mockUsePersonAppearances.mockReturnValue({
      data: MOCK_DATA,
      isLoading: false,
      isError: false,
    });
  });

  it('renders timeline section with month group headings', () => {
    renderPage();
    // January 2024 (video-002) and March 2024 (video-001)
    expect(screen.getByText(/January 2024/i)).toBeTruthy();
    expect(screen.getByText(/March 2024/i)).toBeTruthy();
  });

  it('renders "Unknown Date" group for null recorded_at items at end', () => {
    mockUsePersonAppearances.mockReturnValue({
      data: {
        ...MOCK_DATA,
        results: [
          ...MOCK_DATA.results,
          {
            video_id:         'video-003',
            video_minio_key:  'videos/c.mp4',
            recorded_at:      null,
            duration_sec:     null,
            first_ts_ms:      0,
            appearance_count: 1,
            thumbnail_url:    'https://minio.example.com/frames/thumb3.jpg',
          },
        ],
      },
      isLoading: false,
      isError: false,
    });

    renderPage();

    expect(screen.getByText(/Unknown Date/i)).toBeTruthy();
  });
});
