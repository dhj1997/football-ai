import { MatchCenter } from "@/components/match-center";

export default async function MatchPage({ params }: { params: Promise<{ fixtureId: string }> }) {
  const { fixtureId } = await params;
  return <MatchCenter fixtureId={fixtureId} />;
}
