import path from "node:path";
import type { NextConfig } from "next";

const nextConfig: NextConfig = {
  // Pin the workspace root so a stray lockfile in a parent dir is ignored.
  turbopack: { root: path.resolve(__dirname) },
};

export default nextConfig;
