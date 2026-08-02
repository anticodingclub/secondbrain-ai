import type { NextConfig } from "next";

const nextConfig: NextConfig = {
  // Emits a self-contained server bundle with only the node_modules actually
  // imported at runtime — what docker/frontend.Dockerfile copies.
  output: "standalone",
  // The workspace root is the monorepo, not frontend/; without this Next infers
  // the wrong file-tracing root and warns on every build.
  outputFileTracingRoot: __dirname,
  typedRoutes: true,
};

export default nextConfig;
