import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query';
import { authFetch, getSettings } from './client';
import type { PersonResponse, EnrollResponse, RematchResponse } from '../types/api';

// ── Raw API functions ──────────────────────────────────────────────────────────

export async function listPersons(): Promise<PersonResponse[]> {
  return authFetch('/persons').then(r => r.json());
}

export async function createPerson(name: string): Promise<PersonResponse> {
  return authFetch('/persons', {
    method: 'POST',
    body: JSON.stringify({ name }),
  }).then(r => r.json());
}

export async function enrollPerson(personId: string, formData: FormData): Promise<EnrollResponse> {
  // Do NOT set Content-Type — browser sets multipart boundary automatically
  const { apiBaseUrl, apiToken } = getSettings();
  const prefix = apiBaseUrl || '/api';
  const response = await fetch(`${prefix}/persons/${personId}/enroll`, {
    method: 'POST',
    headers: apiToken ? { Authorization: `Bearer ${apiToken}` } : {},
    body: formData,
  });
  if (!response.ok) {
    const text = await response.text().catch(() => response.statusText);
    throw new Error(`${response.status}: ${text}`);
  }
  return response.json();
}

export async function deletePerson(personId: string): Promise<void> {
  await authFetch(`/persons/${personId}`, { method: 'DELETE' });
}

export async function rematchPerson(personId: string): Promise<RematchResponse> {
  return authFetch(`/persons/${personId}/rematch`, { method: 'POST' }).then(r => r.json());
}

// ── TanStack Query hooks (v5 object-form only) ─────────────────────────────────

export function usePersons() {
  const { apiToken } = getSettings();
  return useQuery({
    queryKey: ['persons'],
    queryFn:  listPersons,
    staleTime: 30_000,
    enabled: !!apiToken,   // don't fire without a token
  });
}

export function useCreatePerson() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: createPerson,
    onSuccess: () => qc.invalidateQueries({ queryKey: ['persons'] }),
  });
}

export function useEnrollPerson(personId: string) {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (formData: FormData) => enrollPerson(personId, formData),
    onSuccess: () => qc.invalidateQueries({ queryKey: ['persons'] }),
  });
}

export function useDeletePerson() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: deletePerson,
    onSuccess: () => qc.invalidateQueries({ queryKey: ['persons'] }),
  });
}

export function useRematchPerson() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: rematchPerson,
    onSuccess: () => qc.invalidateQueries({ queryKey: ['persons'] }),
  });
}
