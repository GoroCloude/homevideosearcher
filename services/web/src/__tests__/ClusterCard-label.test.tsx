/**
 * RED tests for Task 2: ClusterCard inline label display + edit UI
 *
 * These tests will FAIL before implementation because ClusterCard does not yet
 * import useLabelCluster, render label text, or have an inline edit input.
 */
import { describe, it, expect, vi, beforeEach } from 'vitest';
import { render, screen, fireEvent, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import React from 'react';

// ── Hoisted mocks ─────────────────────────────────────────────────────────────
const { mockMutateAsync } = vi.hoisted(() => ({
  mockMutateAsync: vi.fn(),
}));

vi.mock('../api/clusters', async (importOriginal) => {
  const actual = await importOriginal<typeof import('../api/clusters')>();
  return {
    ...actual,
    useLabelCluster: vi.fn(() => ({
      mutate:      vi.fn(),
      mutateAsync: mockMutateAsync,
      isPending:   false,
      isSuccess:   false,
    })),
  };
});

vi.mock('../hooks/useToast', () => ({
  addToast: vi.fn(),
}));

vi.mock('../components/FrameThumbnail', () => ({
  default: () => React.createElement('img', { alt: 'Cluster representative' }),
}));

import ClusterCard from '../components/ClusterCard';
import type { ClusterItem } from '../types/api';
import { addToast } from '../hooks/useToast';

// ── Helpers ───────────────────────────────────────────────────────────────────
function makeCluster(overrides: Partial<ClusterItem> = {}): ClusterItem {
  return {
    id:                      'cluster-abc',
    representative_frame_id: 1,
    appearance_count:        5,
    first_seen:              '2024-01-01T00:00:00Z',
    last_seen:               '2024-06-01T00:00:00Z',
    thumbnail_url:           null,
    ignored:                 false,
    label:                   null,
    ...overrides,
  };
}

function renderCard(cluster: ClusterItem) {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    React.createElement(
      QueryClientProvider,
      { client: qc },
      React.createElement(ClusterCard, { cluster }),
    ),
  );
}

// ── Tests ──────────────────────────────────────────────────────────────────────

describe('ClusterCard label display', () => {
  beforeEach(() => {
    mockMutateAsync.mockReset();
    mockMutateAsync.mockResolvedValue(undefined);
  });

  it('does NOT show "Unknown person" or "Add nickname" text when label is null', () => {
    renderCard(makeCluster({ label: null }));
    expect(screen.queryByText(/unknown person/i)).toBeNull();
    expect(screen.queryByText(/add nickname/i)).toBeNull();
  });

  it('shows label text when label is set', () => {
    renderCard(makeCluster({ label: 'Grandma' }));
    expect(screen.getByText('Grandma')).toBeTruthy();
  });

  it('renders a pencil icon (✏) in the card', () => {
    renderCard(makeCluster({ label: null }));
    // Pencil icon should be present (may be opacity-0 / hover-only)
    expect(screen.getByTitle('Add nickname')).toBeTruthy();
  });
});

describe('ClusterCard label edit', () => {
  beforeEach(() => {
    mockMutateAsync.mockReset();
    mockMutateAsync.mockResolvedValue(undefined);
  });

  it('clicking the label area switches to edit input', async () => {
    renderCard(makeCluster({ label: 'Grandma' }));
    const labelEl = screen.getByText('Grandma');
    // Click parent div
    fireEvent.click(labelEl.parentElement!);
    await waitFor(() => {
      expect(screen.getByRole('textbox')).toBeTruthy();
    });
  });

  it('clicking pencil on null-label card opens edit input', async () => {
    renderCard(makeCluster({ label: null }));
    const pencilContainer = screen.getByTitle('Add nickname');
    fireEvent.click(pencilContainer);
    await waitFor(() => {
      expect(screen.getByRole('textbox')).toBeTruthy();
    });
  });

  it('pressing Enter on input triggers blur which calls mutateAsync', async () => {
    const user = userEvent.setup();
    renderCard(makeCluster({ label: null }));
    // Open edit mode
    fireEvent.click(screen.getByTitle('Add nickname'));
    const input = await screen.findByRole('textbox');
    await user.clear(input);
    await user.type(input, 'Uncle Bob');
    await user.keyboard('{Enter}');
    await waitFor(() => {
      expect(mockMutateAsync).toHaveBeenCalledWith({
        clusterId: 'cluster-abc',
        label:     'Uncle Bob',
      });
    });
  });

  it('blurring with empty input sends null (CLU-04 — clear label)', async () => {
    const user = userEvent.setup();
    renderCard(makeCluster({ label: 'Grandma' }));
    // Open edit mode
    fireEvent.click(screen.getByText('Grandma').parentElement!);
    const input = await screen.findByRole('textbox');
    await user.clear(input);
    fireEvent.blur(input);
    await waitFor(() => {
      expect(mockMutateAsync).toHaveBeenCalledWith({
        clusterId: 'cluster-abc',
        label:     null,
      });
    });
  });

  it('shows "Label saved" toast on successful save', async () => {
    const user = userEvent.setup();
    renderCard(makeCluster({ label: null }));
    fireEvent.click(screen.getByTitle('Add nickname'));
    const input = await screen.findByRole('textbox');
    await user.type(input, 'Aunt Jane');
    fireEvent.blur(input);
    await waitFor(() => {
      expect(addToast).toHaveBeenCalledWith('Label saved', 'success');
    });
  });

  it('shows "Failed to save label" toast on error', async () => {
    mockMutateAsync.mockRejectedValue(new Error('500: Internal Server Error'));
    const user = userEvent.setup();
    renderCard(makeCluster({ label: null }));
    fireEvent.click(screen.getByTitle('Add nickname'));
    const input = await screen.findByRole('textbox');
    await user.type(input, 'Bad Label');
    fireEvent.blur(input);
    await waitFor(() => {
      expect(addToast).toHaveBeenCalledWith('Failed to save label', 'error');
    });
  });

  it('input has maxLength={100}', async () => {
    renderCard(makeCluster({ label: null }));
    fireEvent.click(screen.getByTitle('Add nickname'));
    const input = (await screen.findByRole('textbox')) as HTMLInputElement;
    expect(input.maxLength).toBe(100);
  });

  it('no-op when value is unchanged on blur', async () => {
    renderCard(makeCluster({ label: 'Grandma' }));
    fireEvent.click(screen.getByText('Grandma').parentElement!);
    const input = await screen.findByRole('textbox');
    fireEvent.blur(input); // blur without changing value
    await waitFor(() => {
      expect(mockMutateAsync).not.toHaveBeenCalled();
    });
  });
});
