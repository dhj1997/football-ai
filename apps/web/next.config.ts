import type { NextConfig } from "next";

const nextConfig: NextConfig = {
  output: "standalone",
  allowedDevOrigins: ["127.0.0.1", "localhost"],
  images: {
    remotePatterns: [
      { protocol: "https", hostname: "media.api-sports.io" },
      { protocol: "https", hostname: "r2.thesportsdb.com" },
      { protocol: "https", hostname: "a.espncdn.com" },
      { protocol: "https", hostname: "sd.qunliao.info" },
      { protocol: "https", hostname: "**.dongqiudi.com" },
      { protocol: "https", hostname: "**.dongdianqiu.com" },
      { protocol: "https", hostname: "**.qunliao.info" },
    ],
  },
  reactStrictMode: true,
};

export default nextConfig;
