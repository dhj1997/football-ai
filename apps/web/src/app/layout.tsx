import type { Metadata } from "next";
import Link from "next/link";
import { SiteNav } from "@/components/site-nav";
import "./globals.css";

export const metadata: Metadata = {
  title: "EDGE / FOOTBALL",
  description: "可追溯的足球竞猜研究终端",
};

export default function RootLayout({ children }: Readonly<{ children: React.ReactNode }>) {
  return (
    <html lang="zh-CN">
      <body>
        <span
          hidden
          dangerouslySetInnerHTML={{
            __html:
              "<!-- THESIS: 机场运行屏式的比赛扫读秩序，选择比赛后点亮赛前证据轨道 | SIGNATURE: evidence readiness rail | AVOID: 霓虹博彩盘口墙、装饰性渐变、虚假精确性 | impeccable:seed a76aed7b -->",
          }}
        />
        <header className="app-header">
          <Link className="brand" href="/" aria-label="返回赛程首页">
            <span className="brand-mark" aria-hidden="true">E/F</span>
            <span>
              <strong>EDGE / FOOTBALL</strong>
              <small>足球竞猜研究终端</small>
            </span>
          </Link>
          <SiteNav />
        </header>
        {children}
      </body>
    </html>
  );
}
