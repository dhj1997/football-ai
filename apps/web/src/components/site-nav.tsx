"use client";

import Link from "next/link";
import {
  ChartNoAxesCombined,
  LayoutList,
  Moon,
  Settings2,
  Sun,
  Table2,
} from "lucide-react";
import { usePathname } from "next/navigation";

function ThemeToggle() {
  function toggle() {
    const root = document.documentElement;
    const next = root.dataset.theme === "light" ? "dark" : "light";
    root.dataset.theme = next;
    try {
      localStorage.setItem("theme", next);
    } catch {
      /* 隐私模式下忽略 */
    }
  }
  return (
    <button
      type="button"
      className="theme-toggle"
      onClick={toggle}
      title="切换亮色 / 暗色主题"
      aria-label="切换亮色或暗色主题"
    >
      <Sun className="icon-for-dark" size={16} aria-hidden="true" />
      <Moon className="icon-for-light" size={16} aria-hidden="true" />
    </button>
  );
}

export function SiteNav() {
  const pathname = usePathname();
  return (
    <nav aria-label="主导航">
      <Link
        href="/"
        aria-label="赛程研究"
        aria-current={pathname === "/" ? "page" : undefined}
        title="赛程研究"
      >
        <LayoutList size={16} aria-hidden="true" />
        <span>赛程研究</span>
      </Link>
      <Link
        href="/standings"
        aria-label="积分数据"
        aria-current={pathname === "/standings" ? "page" : undefined}
        title="积分数据"
      >
        <Table2 size={16} aria-hidden="true" />
        <span>积分数据</span>
      </Link>
      <Link
        href="/performance"
        aria-label="模型复盘"
        aria-current={pathname === "/performance" ? "page" : undefined}
        title="模型复盘"
      >
        <ChartNoAxesCombined size={16} aria-hidden="true" />
        <span>模型复盘</span>
      </Link>
      <Link
        href="/admin"
        aria-label="系统管理"
        aria-current={pathname === "/admin" ? "page" : undefined}
        title="系统管理"
      >
        <Settings2 size={16} aria-hidden="true" />
        <span>系统管理</span>
      </Link>
      <ThemeToggle />
    </nav>
  );
}
