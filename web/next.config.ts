import type { NextConfig } from "next";

const nextConfig: NextConfig = {
  /* config options here */
  output:
    process.env.NEXT_OUTPUT === "standalone" ? "standalone" : undefined,
  cacheComponents: true,
  partialPrefetching: true,
  async rewrites() {
    const engine = process.env.ENGINE_INTERNAL_URL;
    if (!engine) return [];

    return [
      { source: "/v1/:path*", destination: `${engine}/v1/:path*` },
      { source: "/health", destination: `${engine}/health` },
    ];
  },
  turbopack: {
    rules: {
      "*.css": {
        loaders: ["@tailwindcss/turbopack"],
        as: "*.css",
      },
    },
  },
};

export default nextConfig;
