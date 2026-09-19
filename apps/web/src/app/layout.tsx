import type { Metadata } from "next";
import Link from "next/link";
import { SiteClock } from "@/components/site-clock";
import { SiteNav } from "@/components/site-nav";
import "./globals.css";

export const metadata: Metadata = {
  title: "绿茵罗盘 · 足球赛前研究终端",
  description: "可追溯、可解释的足球赛前研究终端",
};

export default function RootLayout({
  children,
}: Readonly<{ children: React.ReactNode }>) {
  return (
    <html lang="zh-CN" suppressHydrationWarning>
      <body>
        <span
          hidden
          dangerouslySetInnerHTML={{
            __html:
              "<!-- THESIS: 机场运行屏式的比赛扫读秩序，选择比赛后点亮赛前证据轨道 | SIGNATURE: evidence readiness rail | AVOID: 霓虹博彩盘口墙、装饰性渐变、虚假精确性 | impeccable:seed a76aed7b -->",
          }}
        />
        <header className="sticky top-0 z-50 flex items-center justify-between gap-3 border-b border-slate-800 bg-pitch-900/90 px-4 py-2.5 sm:px-6 sm:py-3 backdrop-blur-md">
          <div className="flex items-center gap-3 sm:gap-5">
            <Link className="flex items-center gap-2.5 sm:gap-3" href="/" aria-label="返回赛程首页">
              <span
                className="grid h-8 w-8 place-items-center rounded-lg bg-gradient-to-tr from-amber-500 to-orange-600 text-base font-bold text-white shadow-lg shadow-amber-500/20 shrink-0"
                aria-hidden="true"
              >
                罗
              </span>
              <span>
                <h1 className="flex items-center gap-1.5 sm:gap-2 text-xs sm:text-sm font-bold tracking-wide text-white">
                  绿茵罗盘
                  <span className="hidden sm:inline-block rounded border border-amber-500/20 bg-amber-500/10 px-1.5 py-0.5 font-mono text-[10px] font-normal text-amber-400">
                    PITCH COMPASS
                  </span>
                  <span className="hidden md:inline-block rounded border border-slate-700 bg-slate-800/60 px-1.5 py-0.5 font-mono text-[10px] font-normal text-slate-400">
                    v0.1.0
                  </span>
                </h1>
                <p className="text-[10px] sm:text-[11px] text-slate-400">足球赛前研究终端</p>
              </span>
            </Link>
            <div className="hidden h-4 w-px bg-slate-800 lg:block" aria-hidden="true" />
            <div className="hidden items-center gap-2 rounded-full border border-emerald-500/20 bg-emerald-500/10 px-2.5 py-1 text-xs text-emerald-400 lg:flex">
              <span className="h-2 w-2 animate-pulse rounded-full bg-emerald-400" aria-hidden="true" />
              <span>实时赛程监测中</span>
            </div>
          </div>
          <div className="flex items-center gap-2 sm:gap-4">
            <SiteNav />
            <div className="hidden xl:block">
              <SiteClock />
            </div>
          </div>
        </header>
        {children}
      </body>
    </html>
  );
}

