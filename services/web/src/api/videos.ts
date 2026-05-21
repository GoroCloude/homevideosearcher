import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query';
import { authFetch, getSettings } from './client';
import type { VideoListResponse, StreamUrlResponse, UploadUrlResponse } from '../types/api';

export async function listVideos(page = 1, pageSize = 50): Promise<VideoListResponse> {
  return authFetch(`/videos?page=${page}&page_size=${pageSize}`).then(r => r.json());
}

export async function getStreamUrl(videoId: string): Promise<StreamUrlResponse> {
  return authFetch(`/videos/${videoId}/stream-url`).then(r => r.json());
}

/** Calls POST /api/videos/upload-url to get a presigned MinIO PUT URL for direct browser upload. */
export async function getUploadUrl(filename: string): Promise<UploadUrlResponse> {
  return authFetch('/videos/upload-url', {
    method: 'POST',
    body: JSON.stringify({ filename }),
  }).then(r => r.json());
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

/**
 * Exposes ingest trigger + ['videos'] query invalidation for post-upload refresh.
 * XHR progress tracking lives in VideoUploadButton — this hook handles the ingest side only.
 */
export function useUploadVideo() {
  const qc = useQueryClient();
  return {
    triggerIngest: async (minioKey: string): Promise<void> => {
      await reIngestVideo(minioKey);
      await qc.invalidateQueries({ queryKey: ['videos'] });
    },
  };
}
