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

/**
 * 各联赛专属高精矢量徽章
 */
export function LeagueIcon({
  league,
  size = 16,
  className = "",
  ...props
}: IconProps & { league: string }) {
  const norm = league.toLowerCase().replace(/[-_\s]/g, "");

  // 英超 (Premier League) - 狮王皇冠
  if (norm === "epl" || norm.includes("premier")) {
    return (
      <svg
        width={size}
        height={size}
        viewBox="0 0 24 24"
        fill="none"
        xmlns="http://www.w3.org/2000/svg"
        className={className}
        aria-hidden="true"
        {...props}
      >
        <circle cx="12" cy="12" r="11" fill="#3D195B" />
        {/* Crown & Lion Motif */}
        <path
          d="M6 9.5L8 14.5L12 11.5L16 14.5L18 9.5L14.5 11L12 7L9.5 11L6 9.5Z"
          fill="#00FF87"
        />
        <circle cx="12" cy="16" r="2" fill="#00FF87" />
        <path d="M10 18.5H14" stroke="#00FF87" strokeWidth="1.2" strokeLinecap="round" />
      </svg>
    );
  }

  // 西甲 (LaLiga) - 动感旋风徽标
  if (norm === "laliga" || norm.includes("liga")) {
    return (
      <svg
        width={size}
        height={size}
        viewBox="0 0 24 24"
        fill="none"
        xmlns="http://www.w3.org/2000/svg"
        className={className}
        aria-hidden="true"
        {...props}
      >
        <circle cx="12" cy="12" r="11" fill="#18181B" stroke="#EA580C" strokeWidth="1" />
        {/* LaLiga Dynamic Sun/Ribbon */}
        <path
          d="M12 4C7.58 4 4 7.58 4 12C4 16.42 7.58 20 12 20C16.42 20 20 16.42 20 12"
          stroke="#EA580C"
          strokeWidth="2.2"
          strokeLinecap="round"
        />
        <circle cx="12" cy="12" r="3.5" fill="#FACC15" />
        <path
          d="M14.5 9.5L18 6"
          stroke="#EF4444"
          strokeWidth="2"
          strokeLinecap="round"
        />
      </svg>
    );
  }

  // 中超 (CSL) - 中国超级联赛火神腾龙徽标
  if (norm === "csl" || norm.includes("superleague") || norm.includes("中超")) {
    return (
      <svg
        width={size}
        height={size}
        viewBox="0 0 24 24"
        fill="none"
        xmlns="http://www.w3.org/2000/svg"
        className={className}
        aria-hidden="true"
        {...props}
      >
        <circle cx="12" cy="12" r="11" fill="#7F1D1D" />
        {/* CSL Flame and Ball */}
        <path
          d="M12 4C12 4 15 7.5 15 10.5C15 13 13.2 14.5 12 15.5C10.8 14.5 9 13 9 10.5C9 7.5 12 4 12 4Z"
          fill="#F59E0B"
        />
        <circle cx="12" cy="16" r="3" fill="#EF4444" stroke="#FDE047" strokeWidth="1" />
        <path d="M7 13C7 16.5 9.2 19 12 19C14.8 19 17 16.5 17 13" stroke="#FDE047" strokeWidth="1.2" strokeLinecap="round" />
      </svg>
    );
  }

  // 欧冠 (UCL) - 经典八星足球 (Starball)
  if (norm === "ucl" || norm.includes("champions") || norm.includes("欧冠")) {
    return (
      <svg
        width={size}
        height={size}
        viewBox="0 0 24 24"
        fill="none"
        xmlns="http://www.w3.org/2000/svg"
        className={className}
        aria-hidden="true"
        {...props}
      >
        <circle cx="12" cy="12" r="11" fill="#0A192F" stroke="#38BDF8" strokeWidth="1" />
        {/* Champions League Stars */}
        <g fill="#F8FAFC">
          {/* Center Star */}
          <polygon points="12,8 13,10.8 16,11.2 13.8,13.2 14.4,16 12,14.6 9.6,16 10.2,13.2 8,11.2 11,10.8" />
          {/* Top Star */}
          <circle cx="12" cy="4.5" r="1" />
          {/* Side Stars */}
          <circle cx="5" cy="10" r="0.9" />
          <circle cx="19" cy="10" r="0.9" />
          <circle cx="7" cy="17" r="0.9" />
          <circle cx="17" cy="17" r="0.9" />
        </g>
      </svg>
    );
  }

  // 亚冠 (ACL) - 亚洲之星与环道
  if (norm === "acl" || norm.includes("afc") || norm.includes("亚冠")) {
    return (
      <svg
        width={size}
        height={size}
        viewBox="0 0 24 24"
        fill="none"
        xmlns="http://www.w3.org/2000/svg"
        className={className}
        aria-hidden="true"
        {...props}
      >
        <circle cx="12" cy="12" r="11" fill="#1E1B4B" stroke="#6366F1" strokeWidth="1" />
        {/* Asian Star Motif */}
        <polygon points="12,5 13.8,9.8 19,10 15,13.5 16.5,18.5 12,15.5 7.5,18.5 9,13.5 5,10 10.2,9.8" fill="#FBBF24" />
        <circle cx="12" cy="12.5" r="2" fill="#4338CA" />
      </svg>
    );
  }

  // 足协杯 (CFA Cup) - 中国足协杯金杯
  if (norm === "cfa_cup" || norm.includes("cfacup") || norm.includes("cup") || norm.includes("杯")) {
    return (
      <svg
        width={size}
        height={size}
        viewBox="0 0 24 24"
        fill="none"
        xmlns="http://www.w3.org/2000/svg"
        className={className}
        aria-hidden="true"
        {...props}
      >
        <circle cx="12" cy="12" r="11" fill="#450A0A" stroke="#DC2626" strokeWidth="1" />
        {/* Gold Trophy */}
        <path
          d="M8 6H16V10C16 12.2 14.2 14 12 14C9.8 14 8 12.2 8 10V6Z"
          fill="#F59E0B"
        />
        <path d="M6 7H8V9C8 9.8 7.3 10.5 6.5 10.5H6V7Z" stroke="#F59E0B" strokeWidth="1.2" />
        <path d="M18 7H16V9C16 9.8 16.7 10.5 17.5 10.5H18V7Z" stroke="#F59E0B" strokeWidth="1.2" />
        <path d="M11 14H13V17H11V14Z" fill="#F59E0B" />
        <rect x="9" y="17" width="6" height="2" rx="0.5" fill="#F59E0B" />
      </svg>
    );
  }

  // 缺省/全部联赛 - 战术球场罗盘徽标
  return (
    <svg
      width={size}
      height={size}
      viewBox="0 0 24 24"
      fill="none"
      xmlns="http://www.w3.org/2000/svg"
      className={className}
      aria-hidden="true"
      {...props}
    >
      <circle cx="12" cy="12" r="11" fill="#064E3B" stroke="#10B981" strokeWidth="1" />
      <circle cx="12" cy="12" r="5" stroke="#34D399" strokeWidth="1.2" />
      <line x1="12" y1="3" x2="12" y2="21" stroke="#34D399" strokeWidth="1" strokeDasharray="1.5 1.5" />
      <polygon points="12,5 14,12 12,10.5 10,12" fill="#FFFFFF" />
      <polygon points="12,19 14,12 12,13.5 10,12" fill="#047857" />
    </svg>
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
