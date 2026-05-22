import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query';
import { authFetch, getSettings } from './client';
import type {
  VideoListResponse,
  StreamUrlResponse,
  UploadUrlResponse,
  VideoDetailItem,
  VideoDetectionItem,
  VideoFaceItem,
} from '../types/api';

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

// ─── Video Detail ────────────────────────────────────────────────────────────

export async function getVideo(id: string): Promise<VideoDetailItem> {
  return authFetch(`/videos/${id}`).then(r => r.json());
}

export async function getVideoDetections(id: string): Promise<VideoDetectionItem[]> {
  return authFetch(`/videos/${id}/detections`).then(r => r.json());
}

export async function getVideoFaces(id: string): Promise<VideoFaceItem[]> {
  return authFetch(`/videos/${id}/faces`).then(r => r.json());
}

export async function deleteVideo(id: string): Promise<void> {
  await authFetch(`/videos/${id}`, { method: 'DELETE' });
  // 204 No Content — do not call .json()
}

// ─── Hooks ───────────────────────────────────────────────────────────────────

export function useVideoDetail(id: string) {
  const { apiToken } = getSettings();
  return useQuery({
    queryKey: ['video', id],
    queryFn:  () => getVideo(id),
    staleTime: 15_000,
    enabled:   !!apiToken && !!id,
  });
}

export function useVideoDetections(id: string) {
  const { apiToken } = getSettings();
  return useQuery({
    queryKey: ['video-detections', id],
    queryFn:  () => getVideoDetections(id),
    staleTime: 15_000,
    enabled:   !!apiToken && !!id,
  });
}

export function useVideoFaces(id: string) {
  const { apiToken } = getSettings();
  return useQuery({
    queryKey: ['video-faces', id],
    queryFn:  () => getVideoFaces(id),
    staleTime: 15_000,
    enabled:   !!apiToken && !!id,
  });
}

export function useDeleteVideo() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (id: string) => deleteVideo(id),
    onSuccess: (_data, id) => {
      qc.invalidateQueries({ queryKey: ['videos'] });
      qc.removeQueries({ queryKey: ['video', id] });
      qc.invalidateQueries({ queryKey: ['search'] });
      qc.invalidateQueries({ queryKey: ['clusters'] });
    },
  });
}
