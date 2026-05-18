// All API response shapes. Derived from services/api/app/ source files.
// Updated when API models change.

export interface DetectionResult {
  class_name:  string;
  confidence:  number;
  bbox:        [number, number, number, number]; // [x1, y1, x2, y2]
}

export interface FaceResult {
  face_detection_id: number;
  matched_person_id: string | null;
  person_name:       string | null;
  match_tier:        'confident' | 'probable' | null;
  match_similarity:  number | null;
  bbox:              [number, number, number, number];
}

export interface FrameResult {
  frame_id:      number;
  video_id:      string;
  ts_ms:         number;
  thumbnail_url: string;   // "/frames/{id}/image" — relative, rendered as <img src="/api/frames/{id}/image">
  detections:    DetectionResult[];
  faces:         FaceResult[];
}

export interface PaginationInfo {
  page:      number;
  page_size: number;
  total:     number;
  has_next:  boolean;
}

export interface SearchResponse {
  results:    FrameResult[];
  pagination: PaginationInfo;
}

export interface SearchRequest {
  person_ids?:           string[];
  classes?:              string[];
  date_from?:            string;   // ISO 8601: "2024-01-01T00:00:00Z"
  date_to?:              string;   // ISO 8601: "2024-12-31T23:59:59Z"
  video_ids?:            string[];
  include_unknown_faces?: boolean;
  min_confidence?:       number;
  page:                  number;
  page_size:             number;
}

export interface PersonResponse {
  id:               string;
  name:             string;
  notes:            string | null;
  created_at:       string;
  enrollment_count: number;
}

export interface EnrollResponse {
  person_id: string;
  enrolled:  number;
  rejected:  Array<{ filename: string; reason: string }>;
  warning:   string | null;
}

export interface RematchResponse {
  person_id: string;
  matched:   number;
}

export interface VideoListItem {
  id:              string;
  minio_key:       string;
  status:          'pending' | 'processing' | 'done' | 'failed';
  error_message:   string | null;
  recorded_at:     string | null;
  duration_sec:    number | null;
  frame_count:     number;
  detection_count: number;
  face_count:      number;
  ingested_at:     string;
}

export interface VideoListResponse {
  results:   VideoListItem[];
  total:     number;
  page:      number;
  page_size: number;
  has_next:  boolean;
}

export interface StreamUrlResponse {
  url: string;
}

export interface ClusterItem {
  id:                      string;
  representative_frame_id: number | null;
  appearance_count:        number;
  first_seen:              string | null;
  last_seen:               string | null;
  thumbnail_url:           string | null;  // "/frames/{id}/image"
}
