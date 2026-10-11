export interface PrioritizedBanner {
  key: string;
  severity: number;
  degraded?: boolean;
}

export function selectVisibleBanners<T extends PrioritizedBanner>(
  banners: readonly T[],
  limit = 2,
): T[] {
  const ordered = [...banners].sort((left, right) => right.severity - left.severity);
  if (ordered.length <= limit) return ordered;

  const degraded = ordered.find((banner) => banner.degraded);
  const visible = ordered.slice(0, limit);
  if (degraded && !visible.includes(degraded) && limit > 0) {
    visible[limit - 1] = degraded;
  }
  return visible.sort((left, right) => right.severity - left.severity);
}
