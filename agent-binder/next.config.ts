import type { NextConfig } from "next";

const nextConfig: NextConfig = {
  // Fix chunk loading errors (Cannot find module './xxx.js')
  webpack: (config, { isServer }) => {
    if (isServer) {
      config.optimization = { ...config.optimization, moduleIds: "deterministic" };
    }
    return config;
  },
  // Disable problematic features that can cause chunk mismatches
};

export default nextConfig;
