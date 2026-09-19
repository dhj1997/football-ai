"use client";

import Link from "next/link";
import {
  ChartNoAxesCombined,
  LayoutList,
  Settings2,
  Table2,
} from "lucide-react";
import { usePathname } from "next/navigation";

const linkClasses =
  "flex items-center gap-1.5 rounded-lg px-2.5 sm:px-3.5 py-1.5 text-xs font-medium text-slate-400 transition-colors hover:text-slate-200 aria-[current=page]:bg-blue-600 aria-[current=page]:text-white aria-[current=page]:shadow-md aria-[current=page]:shadow-blue-600/30 whitespace-nowrap";

export function SiteNav() {
  const pathname = usePathname();
  return (
    <nav
      aria-label="主导航"
      className="flex items-center gap-0.5 sm:gap-1 rounded-xl border border-slate-800 bg-pitch-950 p-1 overflow-x-auto"
    >
      <Link
        href="/"
        aria-label="赛程研究"
        aria-current={pathname === "/" ? "page" : undefined}
        title="赛程研究"
        className={linkClasses}
      >
        <LayoutList size={14} aria-hidden="true" className="shrink-0" />
        <span className="hidden xs:inline sm:inline">赛程研究</span>
        <span className="xs:hidden sm:hidden">赛程</span>
      </Link>
      <Link
        href="/standings"
        aria-label="积分数据"
        aria-current={pathname === "/standings" ? "page" : undefined}
        title="积分数据"
        className={linkClasses}
      >
        <Table2 size={14} aria-hidden="true" className="shrink-0" />
        <span className="hidden xs:inline sm:inline">积分数据</span>
        <span className="xs:hidden sm:hidden">积分</span>
      </Link>
      <Link
        href="/performance"
        aria-label="模型复盘"
        aria-current={pathname === "/performance" ? "page" : undefined}
        title="模型复盘"
        className={linkClasses}
      >
        <ChartNoAxesCombined size={14} aria-hidden="true" className="shrink-0" />
        <span className="hidden xs:inline sm:inline">模型复盘</span>
        <span className="xs:hidden sm:hidden">复盘</span>
      </Link>
      <Link
        href="/admin"
        aria-label="系统管理"
        aria-current={pathname === "/admin" ? "page" : undefined}
        title="系统管理"
        className={linkClasses}
      >
        <Settings2 size={14} aria-hidden="true" className="shrink-0" />
        <span className="hidden xs:inline sm:inline">系统管理</span>
        <span className="xs:hidden sm:hidden">管理</span>
      </Link>
    </nav>
  );
}
