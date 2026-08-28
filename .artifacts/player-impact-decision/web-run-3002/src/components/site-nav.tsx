"use client";

import Link from "next/link";
import { ChartNoAxesCombined, LayoutList, Settings2, Table2 } from "lucide-react";
import { usePathname } from "next/navigation";

export function SiteNav() {
  const pathname = usePathname();
  return (
    <nav aria-label="主导航">
      <Link href="/" aria-label="赛程看板" aria-current={pathname === "/" ? "page" : undefined} title="赛程看板"><LayoutList size={16} aria-hidden="true" /><span>赛程看板</span></Link>
      <Link href="/standings" aria-label="积分榜" aria-current={pathname === "/standings" ? "page" : undefined} title="积分榜">
        <Table2 size={16} aria-hidden="true" /><span>积分榜</span>
      </Link>
      <Link href="/performance" aria-label="模拟绩效" aria-current={pathname === "/performance" ? "page" : undefined} title="模拟绩效">
        <ChartNoAxesCombined size={16} aria-hidden="true" /><span>模拟绩效</span>
      </Link>
      <Link href="/admin" aria-label="操作台" aria-current={pathname === "/admin" ? "page" : undefined} title="操作台">
        <Settings2 size={16} aria-hidden="true" /><span>操作台</span>
      </Link>
    </nav>
  );
}

