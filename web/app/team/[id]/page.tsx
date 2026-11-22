import PlanView from "@/components/PlanView";

export default async function PlanPage({ params }: { params: Promise<{ id: string }> }) {
  const { id } = await params;
  return <PlanView teamId={Number(id)} />;
}
