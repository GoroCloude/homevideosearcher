import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query';
import { authFetch, getSettings } from './client';
import type { VideoListResponse, StreamUrlResponse } from '../types/api';

export async function listVideos(page = 1, pageSize = 50): Promise<VideoListResponse> {
  return authFetch(`/videos?page=${page}&page_size=${pageSize}`).then(r => r.json());
}

export async function getStreamUrl(videoId: string): Promise<StreamUrlResponse> {
  return authFetch(`/videos/${videoId}/stream-url`).then(r => r.json());
}

/** Calls POST /ingest-api/ingest on ingestion-worker via nginx proxy (nginx.conf: /ingest-api/ → ingestion-worker:8001). */
export async function reIngestVideo(minioKey: string): Promise<void> {
  const { apiToken } = getSettings();
  const response = await fetch('/ingest-api/ingest', {
    method: 'POST',
    headers: {
      'Content-Type': 'application/json',
      ...(apiToken ? { Authorization: `Bearer ${apiToken}` } : {}),
    },
    body: JSON.stringify({ minio_key: minioKey, force: true }),
  });
  if (!response.ok) {
    const text = await response.text().catch(() => response.statusText);
    throw new Error(`${response.status}: ${text}`);
  }
}

export function useVideos(page = 1) {
  const { apiToken } = getSettings();
  return useQuery({
    queryKey: ['videos', page],
    queryFn:  () => listVideos(page),
    staleTime: 15_000,
    enabled:   !!apiToken,
  });
}

export function useReIngestVideo() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (minioKey: string) => reIngestVideo(minioKey),
    onSuccess: () => qc.invalidateQueries({ queryKey: ['videos'] }),
  });
}
