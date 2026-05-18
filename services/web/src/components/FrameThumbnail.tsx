import { useState } from 'react';
import { getFrameImageUrl } from '../api/frames';
import clsx from 'clsx';

interface Props {
  frameId:    number;
  alt?:       string;
  className?: string;
  onClick?:   () => void;
}

export default function FrameThumbnail({ frameId, alt = 'Frame', className, onClick }: Props) {
  const [loaded, setLoaded] = useState(false);
  const [error,  setError]  = useState(false);

  return (
    <div
      className={clsx('relative overflow-hidden bg-gray-200 rounded', className)}
      onClick={onClick}
      role={onClick ? 'button' : undefined}
      tabIndex={onClick ? 0 : undefined}
      onKeyDown={onClick ? (e) => e.key === 'Enter' && onClick() : undefined}
    >
      {/* Skeleton — shown while loading */}
      {!loaded && !error && (
        <div className="absolute inset-0 animate-pulse bg-gray-300" aria-hidden="true" />
      )}

      {/* Error state */}
      {error && (
        <div className="absolute inset-0 flex items-center justify-center text-gray-400 text-xs">
          ⚠ No image
        </div>
      )}

      {/* The actual thumbnail — <img> handles 302 redirect to MinIO presigned URL */}
      {!error && (
        <img
          src={getFrameImageUrl(frameId)}
          alt={alt}
          loading="lazy"
          className={clsx(
            'w-full h-full object-cover transition-opacity duration-200',
            loaded ? 'opacity-100' : 'opacity-0',
          )}
          onLoad={() => setLoaded(true)}
          onError={() => { setError(true); setLoaded(true); }}
        />
      )}
    </div>
  );
}
