import clsx from 'clsx';

type VideoStatus = 'pending' | 'processing' | 'done' | 'failed';

interface Props {
  status: VideoStatus | string;
}

const STATUS_CONFIG: Record<VideoStatus, { label: string; classes: string }> = {
  pending:    { label: 'Pending',    classes: 'bg-gray-100 text-gray-600' },
  processing: { label: 'Processing', classes: 'bg-blue-100 text-blue-700 animate-pulse' },
  done:       { label: 'Done',       classes: 'bg-green-100 text-green-700' },
  failed:     { label: 'Failed',     classes: 'bg-red-100 text-red-700' },
};

export default function StatusBadge({ status }: Props) {
  const config = STATUS_CONFIG[status as VideoStatus] ?? {
    label: status,
    classes: 'bg-gray-100 text-gray-500',
  };

  return (
    <span
      className={clsx(
        'inline-flex items-center px-2 py-0.5 rounded-full text-xs font-medium',
        config.classes,
      )}
    >
      {config.label}
    </span>
  );
}
