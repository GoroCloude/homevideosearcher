import { useState, useRef, useCallback } from 'react';
import { getUploadUrl, reIngestVideo } from '../api/videos';
import { addToast } from '../hooks/useToast';

const MAX_SIZE = 1_073_741_824; // 1 GB in bytes (UPLOAD-03)

interface Props {
  /** Called after each file's ingest trigger succeeds. Use to invalidate ['videos'] query. */
  onUploadComplete?: () => void;
  /** Called on every XHR progress tick with overall queue percentage 0–100.
   *  Called with 0 when the queue finishes (to hide the progress bar). */
  onProgressChange?: (pct: number) => void;
}

/**
 * Wraps XMLHttpRequest in a Promise for direct MinIO PUT upload.
 * fetch cannot track upload progress — XHR is required here.
 * onProgress receives loaded bytes (not %); caller calculates % from total bytes.
 */
function uploadToMinIO(
  file: File,
  presignedUrl: string,
  onProgress: (loadedBytes: number) => void,
): Promise<void> {
  return new Promise((resolve, reject) => {
    const xhr = new XMLHttpRequest();
    xhr.upload.addEventListener('progress', (e: ProgressEvent) => {
      if (e.lengthComputable) onProgress(e.loaded);
    });
    xhr.addEventListener('load', () => {
      if (xhr.status >= 200 && xhr.status < 300) resolve();
      else reject(new Error(`PUT failed: HTTP ${xhr.status}`));
    });
    xhr.addEventListener('error', () => reject(new Error('Network error during upload')));
    xhr.addEventListener('abort', () => reject(new Error('Upload aborted')));
    xhr.open('PUT', presignedUrl);
    // Content-Type informs MinIO; presigned URL is self-authenticating — do NOT add Authorization header.
    xhr.setRequestHeader('Content-Type', file.type || 'application/octet-stream');
    xhr.send(file);
  });
}

export default function VideoUploadButton({ onUploadComplete, onProgressChange }: Props) {
  const [isUploading, setIsUploading]   = useState(false);
  const [buttonLabel, setButtonLabel]   = useState<string>('Upload Video');
  const fileInputRef = useRef<HTMLInputElement>(null);

  const handleFiles = useCallback(async (fileList: FileList) => {
    const fileArray = Array.from(fileList);

    // UPLOAD-03: Client-side validation — reject before any network request.
    const valid: File[] = [];
    for (const f of fileArray) {
      if (f.size === 0) {
        addToast(`'${f.name}' is empty`, 'error');
        continue;
      }
      if (f.size > MAX_SIZE) {
        addToast(`'${f.name}' is too large (max 1 GB)`, 'error');
        continue;
      }
      valid.push(f);
    }
    if (valid.length === 0) return; // all rejected — zero network requests made

    setIsUploading(true);
    setButtonLabel('Uploading…'); // D-10

    const totalBytes      = valid.reduce((sum, f) => sum + f.size, 0);
    let   completedBytes  = 0;
    let   successCount    = 0;

    // UPLOAD-04: Sequential queue — await each file before starting the next.
    for (const file of valid) {
      try {
        // 1. Get presigned PUT URL from API (UPLOAD-01)
        const { url, key } = await getUploadUrl(file.name);

        // 2. Upload directly to MinIO via XHR; track overall queue progress (D-08)
        await uploadToMinIO(file, url, (loadedBytes) => {
          const pct = ((completedBytes + loadedBytes) / totalBytes) * 100;
          onProgressChange?.(pct);
        });
        completedBytes += file.size;
        onProgressChange?.((completedBytes / totalBytes) * 100);

        // 3. Auto-ingest trigger (UPLOAD-05): force=true handles overwrite of duplicate filenames
        try {
          await reIngestVideo(key); // key = "videos/filename.mp4"; reIngestVideo sends force:true
          successCount++;
          addToast(`'${file.name}' uploaded — ingestion started`, 'success'); // UPLOAD-06 success
          onUploadComplete?.(); // caller invalidates ['videos'] query cache
        } catch {
          // Upload to MinIO succeeded but ingest trigger failed (UPLOAD-06 ingest-failure)
          // Use 'info' — 'warning' type does not exist in toast system
          addToast(`'${file.name}' uploaded but ingestion could not be started`, 'info');
        }
      } catch (err) {
        // PUT to MinIO failed — D-01: continue with remaining files; do not abort queue
        const msg = err instanceof Error ? err.message : 'Unknown error';
        addToast(`Upload failed for '${file.name}': ${msg}`, 'error'); // UPLOAD-06 PUT failure
        completedBytes += file.size; // advance bytes so bar doesn't freeze on failure
      }
    }

    // D-02: summary label persists until user picks new files
    setButtonLabel(`${successCount}/${valid.length} uploaded`);
    setIsUploading(false);
    onProgressChange?.(0); // D-09: signal bar to hide (VideosPage shows bar only when pct > 0)
  }, [onUploadComplete, onProgressChange]);

  return (
    <>
      <input
        ref={fileInputRef}
        type="file"
        multiple
        accept="video/*"
        className="hidden"
        onChange={e => {
          if (e.target.files?.length) {
            setButtonLabel('Upload Video'); // D-02: reset label whenever new files are selected
            handleFiles(e.target.files);
          }
          // Reset value so selecting the same file again triggers onChange
          e.target.value = '';
        }}
      />
      <button
        onClick={() => fileInputRef.current?.click()}
        disabled={isUploading}
        className="px-3 py-1.5 text-sm bg-blue-600 text-white rounded-lg hover:bg-blue-700 disabled:opacity-50 disabled:cursor-not-allowed font-medium transition-colors"
      >
        {buttonLabel}
      </button>
    </>
  );
}
