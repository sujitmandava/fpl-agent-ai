import { notFound } from "next/navigation";
import Shell from "@/components/Shell";

export default async function TeamLayout({
  children,
  params,
}: {
  children: React.ReactNode;
  params: Promise<{ id: string }>;
}) {
  const { id } = await params;
  const teamId = Number(id);
  if (!/^\d+$/.test(id) || !Number.isSafeInteger(teamId) || teamId <= 0) notFound();
  return <Shell teamId={teamId}>{children}</Shell>;
}
