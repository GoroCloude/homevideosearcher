import { Link } from 'react-router-dom';
import { useQueryClient } from '@tanstack/react-query';
import { useClusters } from '../api/clusters';
import { useSettings } from '../context/SettingsContext';
import ClusterCard from '../components/ClusterCard';

export default function ClustersPage() {
  const { settings }    = useSettings();
  const queryClient     = useQueryClient();
  const { data: clusters = [], isLoading, isError, error } = useClusters();

  // No-token banner
  if (!settings.apiToken) {
    return (
      <div className="p-6">
        <div className="bg-amber-50 border border-amber-200 rounded-lg p-4 text-sm text-amber-800">
          API token not configured.{' '}
          <Link to="/settings" className="font-medium underline">Go to Settings →</Link>
        </div>
      </div>
    );
  }

  function handleClusterEnrolled() {
    // Refresh clusters list after a cluster is enrolled as a person
    queryClient.invalidateQueries({ queryKey: ['clusters'] });
    queryClient.invalidateQueries({ queryKey: ['persons'] });
  }

  return (
    <div className="p-4 md:p-6">
      <div className="flex items-center justify-between mb-5">
        <h1 className="text-lg font-semibold text-gray-900">Unknown Clusters</h1>
        {clusters.length > 0 && (
          <span className="text-sm text-gray-500">{clusters.length} cluster{clusters.length !== 1 ? 's' : ''}</span>
        )}
      </div>

      {/* Loading skeletons */}
      {isLoading && (
        <div className="grid grid-cols-1 sm:grid-cols-2 md:grid-cols-3 xl:grid-cols-4 gap-4">
          {Array.from({ length: 8 }).map((_, i) => (
            <div key={i} className="aspect-[4/5] bg-gray-200 rounded-xl animate-pulse" />
          ))}
        </div>
      )}

      {/* Error */}
      {isError && (
        <div className="bg-red-50 border border-red-200 rounded-lg p-4 text-sm text-red-700">
          Failed to load clusters: {error instanceof Error ? error.message : 'Unknown error'}
        </div>
      )}

      {/* Empty / coming soon */}
      {!isLoading && !isError && clusters.length === 0 && (
        <div className="bg-blue-50 border border-blue-200 rounded-xl p-8 flex flex-col items-center text-center gap-3 max-w-md mx-auto mt-8">
          <span className="text-4xl">🔮</span>
          <h2 className="font-semibold text-blue-900">Unknown face clustering — Phase 3</h2>
          <p className="text-sm text-blue-700">
            Nightly HDBSCAN clustering of unrecognized faces will appear here once Phase 3
            is deployed. Recurring strangers will be automatically grouped with appearance
            counts and representative thumbnails.
          </p>
          <p className="text-xs text-blue-500 mt-1">
            No clusters yet, or the clustering endpoint is not yet available.
          </p>
        </div>
      )}

      {/* Cluster grid */}
      {clusters.length > 0 && (
        <div className="grid grid-cols-1 sm:grid-cols-2 md:grid-cols-3 xl:grid-cols-4 gap-4">
          {clusters.map(cluster => (
            <ClusterCard
              key={cluster.id}
              cluster={cluster}
              onEnrolled={handleClusterEnrolled}
            />
          ))}
        </div>
      )}
    </div>
  );
}
