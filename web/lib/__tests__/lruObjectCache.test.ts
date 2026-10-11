import { describe, expect, it, vi } from "vitest";
import { LruObjectCache } from "../lruObjectCache";

describe("LruObjectCache", () => {
  it("evicts the least recently used value and disposes it", () => {
    const dispose = vi.fn();
    const cache = new LruObjectCache(2, dispose);
    const first = {};
    const second = {};
    const third = {};
    cache.set("first", first);
    cache.set("second", second);
    cache.get("first");
    cache.set("third", third);
    expect(cache.get("first")).toBe(first);
    expect(cache.get("second")).toBeUndefined();
    expect(dispose).toHaveBeenCalledTimes(1);
    expect(dispose).toHaveBeenCalledWith(second);
  });

  it("disposes all retained values when cleared", () => {
    const dispose = vi.fn();
    const cache = new LruObjectCache(2, dispose);
    cache.set("a", {});
    cache.set("b", {});
    cache.clear();
    expect(dispose).toHaveBeenCalledTimes(2);
  });
});
