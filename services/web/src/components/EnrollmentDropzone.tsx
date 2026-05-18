import { useState, useRef } from 'react';
import clsx from 'clsx';
import { useEnrollPerson } from '../api/persons';

interface RejectedFile {
  filename: string;
  reason:   string;
}

interface Props {
  personId:  string;
  onSuccess?: (enrolled: number) => void;
}

export default function EnrollmentDropzone({ personId, onSuccess }: Props) {
  const [files,     setFiles]     = useState<File[]>([]);
  const [dragOver,  setDragOver]  = useState(false);
  const [rejected,  setRejected]  = useState<RejectedFile[]>([]);
  const [warning,   setWarning]   = useState<string | null>(null);
  const [previews,  setPreviews]  = useState<string[]>([]);
  const fileInputRef = useRef<HTMLInputElement>(null);

  const enroll = useEnrollPerson(personId);

  function addFiles(incoming: File[]) {
    const imageFiles = incoming.filter(f => f.type.startsWith('image/'));
    if (imageFiles.length === 0) return;

    setFiles(prev => {
      const next = [...prev, ...imageFiles];
      // Generate previews for new files only
      imageFiles.forEach(f => {
        const reader = new FileReader();
        reader.onload = e => {
          setPreviews(ps => [...ps, e.target?.result as string]);
        };
        reader.readAsDataURL(f);
      });
      return next;
    });
    setRejected([]);
    setWarning(null);
  }

  function removeFile(index: number) {
    setFiles(prev => prev.filter((_, i) => i !== index));
    setPreviews(prev => prev.filter((_, i) => i !== index));
  }

  async function handleSubmit() {
    if (files.length === 0) return;

    const formData = new FormData();
    files.forEach(f => formData.append('images', f, f.name));

    const result = await enroll.mutateAsync(formData);
    setRejected(result.rejected);
    setWarning(result.warning);

    if (result.enrolled > 0) {
      // Clear accepted files; keep rejected ones visible
      const rejectedNames = new Set(result.rejected.map(r => r.filename));
      setFiles(prev => prev.filter(f => rejectedNames.has(f.name)));
      setPreviews(prev => {
        const originalFiles = files;
        return prev.filter((_, i) => rejectedNames.has(originalFiles[i]?.name ?? ''));
      });
      onSuccess?.(result.enrolled);
    }
  }

  return (
    <div className="space-y-3">
      {/* Drop zone */}
      <div
        onDragOver={(e) => { e.preventDefault(); setDragOver(true); }}
        onDragLeave={() => setDragOver(false)}
        onDrop={(e) => {
          e.preventDefault();
          setDragOver(false);
          addFiles(Array.from(e.dataTransfer.files));
        }}
        onClick={() => fileInputRef.current?.click()}
        className={clsx(
          'border-2 border-dashed rounded-lg p-8 text-center cursor-pointer transition-colors select-none',
          dragOver ? 'border-blue-500 bg-blue-50' : 'border-gray-300 hover:border-gray-400 hover:bg-gray-50',
        )}
      >
        <input
          ref={fileInputRef}
          type="file"
          multiple
          accept="image/*"
          className="hidden"
          onChange={e => addFiles(Array.from(e.target.files ?? []))}
        />
        <p className="text-sm text-gray-500">
          {dragOver
            ? 'Drop images here…'
            : 'Drop images here or click to browse'}
        </p>
        <p className="text-xs text-gray-400 mt-1">
          Accepts JPEG, PNG, WebP · 5+ images recommended for best accuracy
        </p>
      </div>

      {/* File preview grid */}
      {files.length > 0 && (
        <div className="grid grid-cols-4 gap-2">
          {files.map((file, i) => (
            <div key={i} className="relative group">
              {previews[i] && (
                <img
                  src={previews[i]}
                  alt={file.name}
                  className="w-full aspect-square object-cover rounded border border-gray-200"
                />
              )}
              <button
                onClick={() => removeFile(i)}
                className="absolute top-0.5 right-0.5 bg-black/60 text-white rounded-full w-4 h-4 text-xs flex items-center justify-center opacity-0 group-hover:opacity-100 transition-opacity"
                aria-label={`Remove ${file.name}`}
              >
                ×
              </button>
              <p className="text-xs text-gray-500 truncate mt-0.5">{file.name}</p>
            </div>
          ))}
        </div>
      )}

      {/* Warning: fewer than 5 images */}
      {warning && (
        <div className="bg-amber-50 border border-amber-200 rounded p-3 text-xs text-amber-700">
          ⚠ {warning}
        </div>
      )}

      {/* Per-file rejection reasons */}
      {rejected.length > 0 && (
        <div className="bg-red-50 border border-red-200 rounded p-3 space-y-1">
          <p className="text-xs font-semibold text-red-700">Rejected images:</p>
          {rejected.map((r, i) => (
            <p key={i} className="text-xs text-red-600">
              <span className="font-medium">{r.filename}</span>: {r.reason}
            </p>
          ))}
        </div>
      )}

      {/* Submit button */}
      {files.length > 0 && (
        <button
          onClick={handleSubmit}
          disabled={enroll.isPending || files.length === 0}
          className="w-full py-2 bg-blue-600 text-white text-sm font-medium rounded-lg hover:bg-blue-700 disabled:opacity-50 disabled:cursor-not-allowed transition-colors"
        >
          {enroll.isPending
            ? 'Uploading…'
            : `Upload ${files.length} image${files.length !== 1 ? 's' : ''}`}
        </button>
      )}
    </div>
  );
}
