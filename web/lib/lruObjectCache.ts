export class LruObjectCache<T extends object> {
  private readonly values = new Map<string, T>();

  constructor(
    private readonly capacity: number,
    private readonly onEvict: (value: T) => void = () => undefined,
  ) {
    if (!Number.isInteger(capacity) || capacity < 1) {
      throw new RangeError("Cache capacity must be a positive integer");
    }
  }

  get(key: string): T | undefined {
    const value = this.values.get(key);
    if (value) {
      this.values.delete(key);
      this.values.set(key, value);
    }
    return value;
  }

  set(key: string, value: T): void {
    const previous = this.values.get(key);
    if (previous) this.onEvict(previous);
    this.values.delete(key);
    this.values.set(key, value);
    while (this.values.size > this.capacity) {
      const oldestKey = this.values.keys().next().value;
      if (oldestKey === undefined) break;
      const oldest = this.values.get(oldestKey);
      this.values.delete(oldestKey);
      if (oldest) this.onEvict(oldest);
    }
  }

  clear(): void {
    for (const value of this.values.values()) this.onEvict(value);
    this.values.clear();
  }
}
