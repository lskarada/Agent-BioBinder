import type { NextConfig } from "next";

const nextConfig: NextConfig = {
  webpack: (config, { isServer }) => {
    if (isServer) {
      config.optimization = { ...config.optimization, moduleIds: "deterministic" };
    }
    return config;
  },
  async rewrites() {
    return [
      {
        source: "/outputs/:path*",
        destination: "http://localhost:8000/outputs/:path*",
      },
      {
        source: "/api/:path*",
        destination: "http://localhost:8000/:path*",
      },
    ];
  },
};

export default nextConfig;
