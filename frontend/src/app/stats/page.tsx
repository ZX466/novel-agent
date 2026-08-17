import { StatsDashboard } from "@/components/StatsDashboard";

export const metadata = { title: "写作统计" };

export default function StatsPage() {
  return (
    <main className="flex flex-col h-full overflow-hidden" style={{ background: "var(--bg)" }}>
      <div className="px-sp-6 py-sp-5 shrink-0">
        <h1 className="font-display text-lg font-semibold" style={{ color: "var(--fg)", letterSpacing: "-0.01em" }}>
          写作统计
        </h1>
        <p className="text-[11px] mt-sp-0.5" style={{ color: "var(--muted)" }}>
          字数曲线 · 连续天数 · 每日目标
        </p>
      </div>
      <div className="flex-1 overflow-y-auto min-h-0 px-sp-6 pb-sp-6">
        <StatsDashboard />
      </div>
    </main>
  );
}
