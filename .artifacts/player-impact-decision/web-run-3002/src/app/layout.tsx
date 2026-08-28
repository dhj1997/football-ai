import type { Metadata } from "next";
import Link from "next/link";
import { Activity } from "lucide-react";
import { SiteNav } from "@/components/site-nav";
import "./globals.css";

export const metadata: Metadata = {
  title: "足球赛前分析台",
  description: "中超、西甲与英超的可追溯赛前预测工作台",
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
            <span className="brand-mark"><Activity size={19} aria-hidden="true" /></span>
            <span>
              <strong>足球赛前分析台</strong>
              <small>PRE-MATCH DESK</small>
            </span>
          </Link>
          <SiteNav />
        </header>
        {children}
      </body>
    </html>
  );
}
