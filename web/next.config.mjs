import path from "node:path";
import { fileURLToPath } from "node:url";

const __dirname = path.dirname(fileURLToPath(import.meta.url));

/** @type {import('next').NextConfig} */
const nextConfig = {
  reactStrictMode: true,
  poweredByHeader: false,
  compress: true,
  // Pin the file-tracing root to this app so a stray parent lockfile doesn't
  // get inferred as the workspace root.
  outputFileTracingRoot: __dirname,
  webpack(config, { isServer }) {
    // Foxglove decompressors fetch their WASM binary by URL at runtime.
    config.module.rules.push({ test: /\.wasm$/, type: "asset/resource", generator: { filename: "static/wasm/[contenthash][ext]" } });
    if (!isServer) config.resolve.fallback = { ...config.resolve.fallback, fs: false, path: false };
    return config;
  },
};

export default nextConfig;
