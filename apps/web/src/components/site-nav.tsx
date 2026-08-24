"use client";

import Link from "next/link";
import { Settings2 } from "lucide-react";
import { usePathname } from "next/navigation";

export function SiteNav() {
  const pathname = usePathname();
  return (
    <nav aria-label="主导航">
      <Link href="/" aria-current={pathname === "/" ? "page" : undefined}>赛程看板</Link>
      <Link href="/admin" aria-current={pathname === "/admin" ? "page" : undefined}>
        <Settings2 size={16} aria-hidden="true" />操作台
      </Link>
    </nav>
  );
}

