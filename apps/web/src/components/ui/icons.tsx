import type { SVGProps } from "react";

export interface IconProps extends SVGProps<SVGSVGElement> {
  size?: number | string;
  className?: string;
}

/**
 * 绿茵罗盘专属品牌矢量图标
 * 结合战术中圈、经纬刻度与指南针星芒
 */
export function PitchCompassLogo({ size = 32, className = "", ...props }: IconProps) {
  return (
    <svg
      width={size}
      height={size}
      viewBox="0 0 32 32"
      fill="none"
      xmlns="http://www.w3.org/2000/svg"
      className={className}
      aria-hidden="true"
      {...props}
    >
      <defs>
        <linearGradient id="logoBgGrad" x1="0" y1="0" x2="32" y2="32" gradientUnits="userSpaceOnUse">
          <stop stopColor="#10B981" />
          <stop offset="1" stopColor="#0D9488" />
        </linearGradient>
        <linearGradient id="needleNorthGrad" x1="16" y1="5" x2="16" y2="16" gradientUnits="userSpaceOnUse">
          <stop stopColor="#FFFFFF" />
          <stop offset="1" stopColor="#D1FAE5" />
        </linearGradient>
        <linearGradient id="needleSouthGrad" x1="16" y1="16" x2="16" y2="27" gradientUnits="userSpaceOnUse">
          <stop stopColor="#044E3A" />
          <stop offset="1" stopColor="#065F46" />
        </linearGradient>
      </defs>

      {/* 渐变圆角底板 */}
      <rect width="32" height="32" rx="8" fill="url(#logoBgGrad)" />

      {/* 足球中圈与球场标线 */}
      <circle cx="16" cy="16" r="10" stroke="#FFFFFF" strokeWidth="1.2" strokeOpacity="0.3" />
      <line x1="16" y1="3" x2="16" y2="29" stroke="#FFFFFF" strokeWidth="0.8" strokeOpacity="0.2" strokeDasharray="2 2" />
      <line x1="3" y1="16" x2="29" y2="16" stroke="#FFFFFF" strokeWidth="0.8" strokeOpacity="0.2" strokeDasharray="2 2" />

      {/* 罗盘刻度外环 */}
      <circle cx="16" cy="16" r="7.2" stroke="#FFFFFF" strokeWidth="1.3" strokeOpacity="0.85" />

      {/* 指南针指针 (北针) */}
      <polygon points="16,5.5 19,16 16,13.8 13,16" fill="url(#needleNorthGrad)" />
      {/* 指南针指针 (南针) */}
      <polygon points="16,26.5 19,16 16,18.2 13,16" fill="url(#needleSouthGrad)" />

      {/* 中心枢轴 */}
      <circle cx="16" cy="16" r="2.2" fill="#FFFFFF" />
      <circle cx="16" cy="16" r="1.1" fill="#0F766E" />
    </svg>
  );
}

/** Render a source-backed competition badge; unknown competitions stay textual. */
export function LeagueIcon({
  league,
  size = 16,
  className = "",
  logoUrl,
}: IconProps & { league: string; logoUrl?: string | null }) {
  const logoByLeague: Record<string, string> = {
    epl: "https://media.api-sports.io/football/leagues/39.png",
    laliga: "https://media.api-sports.io/football/leagues/140.png",
    csl: "https://media.api-sports.io/football/leagues/169.png",
    cfa_cup: "https://media.api-sports.io/football/leagues/171.png",
    ucl: "https://media.api-sports.io/football/leagues/2.png",
    world_cup: "https://media.api-sports.io/football/leagues/1.png",
    international_friendlies: "https://media.api-sports.io/football/leagues/10.png",
    asian_cup: "https://media.api-sports.io/football/leagues/7.png",
    asian_qualifiers: "https://media.api-sports.io/football/leagues/35.png",
    afc_u23_asian_cup: "https://media.api-sports.io/football/leagues/532.png",
    afc_u23_qualifiers: "https://media.api-sports.io/football/leagues/952.png",
    asian_games_men: "https://media.api-sports.io/football/leagues/803.png",
    euro: "https://media.api-sports.io/football/leagues/4.png",
    euro_qualifiers: "https://media.api-sports.io/football/leagues/960.png",
    copa_america: "https://media.api-sports.io/football/leagues/9.png",
    africa_cup: "https://media.api-sports.io/football/leagues/6.png",
    africa_qualifiers: "https://media.api-sports.io/football/leagues/36.png",
    nations_league: "https://media.api-sports.io/football/leagues/5.png",
  };
  const source = logoUrl ?? logoByLeague[league.toLowerCase()];
  if (source) {
    return (
      // Source badges are provider-hosted URLs; keep the provider asset intact.
      // eslint-disable-next-line @next/next/no-img-element
      <img
        src={source}
        width={size}
        height={size}
        className={`object-contain ${className}`}
        alt=""
        aria-hidden="true"
      />
    );
  }
  return (
    <span
      className={`inline-flex shrink-0 items-center justify-center rounded border border-slate-600 bg-slate-800 px-1 font-mono text-[9px] font-bold leading-none text-slate-300 ${className}`}
      style={{ width: size, height: size }}
      aria-hidden="true"
      title="赛事图标暂无源站图片"
    >
      {league.replace(/_/g, " ").slice(0, 3).toUpperCase()}
    </span>
  );
}

/**
 * 球队队徽缺省盾牌徽标
 * 当官方图片缺失时，展示精致主客场战术队徽盾牌
 */
export function TeamShieldPlaceholder({
  name,
  code,
  tone = "home",
  size = 28,
  className = "",
}: {
  name: string;
  code?: string | null;
  tone?: "home" | "away";
  size?: number;
  className?: string;
}) {
  const isHome = tone === "home";
  const displayLetter = (code && code.trim() ? code.trim() : name).slice(0, 3).toUpperCase();

  return (
    <div
      className={`relative inline-flex items-center justify-center shrink-0 select-none overflow-hidden rounded-lg shadow-sm border ${
        isHome
          ? "border-blue-500/40 bg-gradient-to-b from-blue-950 to-slate-900 text-blue-300"
          : "border-slate-700 bg-gradient-to-b from-slate-800 to-slate-950 text-slate-300"
      } ${className}`}
      style={{ width: size, height: size }}
      title={name}
      aria-hidden="true"
    >
      {/* 战术盾牌微底纹 */}
      <svg
        className="absolute inset-0 h-full w-full opacity-15"
        viewBox="0 0 32 32"
        fill="none"
        xmlns="http://www.w3.org/2000/svg"
      >
        <path
          d="M16 3L6 7V15C6 21.5 10.3 27.5 16 29C21.7 27.5 26 21.5 26 15V7L16 3Z"
          stroke="currentColor"
          strokeWidth="2"
        />
        <circle cx="16" cy="16" r="4" stroke="currentColor" strokeWidth="1" />
      </svg>
      {/* 球队简写 */}
      <span className="relative z-10 font-mono font-bold tracking-tight text-[10px] tabular-nums text-center px-0.5 leading-none">
        {displayLetter}
      </span>
    </div>
  );
}
