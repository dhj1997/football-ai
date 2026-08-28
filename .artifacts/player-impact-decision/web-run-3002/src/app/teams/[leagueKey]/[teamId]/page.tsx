import { TeamDashboard } from "@/components/team-dashboard";

export default async function TeamPage({
  params,
}: {
  params: Promise<{ leagueKey: string; teamId: string }>;
}) {
  const { leagueKey, teamId } = await params;
  return <TeamDashboard leagueKey={leagueKey} teamId={teamId} />;
}
