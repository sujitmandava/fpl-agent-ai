import LeagueView from "@/components/LeagueView";

export default async function LeaguePage({ params }: { params: Promise<{ id: string }> }) {
  const { id } = await params;
  return <LeagueView teamId={Number(id)} />;
}
