import { useQuery, useQueryClient } from '@tanstack/react-query';
import { getMetrics } from '@/shared';

export function useMetrics() {
  const qc = useQueryClient();
  const { data: metrics = null, isFetching } = useQuery({
    queryKey: ['metrics'],
    queryFn: getMetrics,
    staleTime: 60_000,
  });

  return {
    metrics,
    loading: isFetching,
    refresh: () => qc.invalidateQueries({ queryKey: ['metrics'] }),
  };
}
