"use client";

import Link from "next/link";
import { ChartNoAxesCombined, LayoutList, Settings2, Table2 } from "lucide-react";
import { usePathname } from "next/navigation";

export function SiteNav() {
  const pathname = usePathname();
  return (
    <nav aria-label="主导航">
      <Link href="/" aria-label="赛程研究" aria-current={pathname === "/" ? "page" : undefined} title="赛程研究"><LayoutList size={16} aria-hidden="true" /><span>赛程研究</span></Link>
      <Link href="/standings" aria-label="积分数据" aria-current={pathname === "/standings" ? "page" : undefined} title="积分数据">
        <Table2 size={16} aria-hidden="true" /><span>积分数据</span>
      </Link>
      <Link href="/performance" aria-label="模型复盘" aria-current={pathname === "/performance" ? "page" : undefined} title="模型复盘">
        <ChartNoAxesCombined size={16} aria-hidden="true" /><span>模型复盘</span>
      </Link>
      <Link href="/admin" aria-label="系统管理" aria-current={pathname === "/admin" ? "page" : undefined} title="系统管理">
        <Settings2 size={16} aria-hidden="true" /><span>系统管理</span>
      </Link>
    </nav>
  );
}

