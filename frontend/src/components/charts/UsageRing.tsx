import {
  PolarAngleAxis,
  RadialBar,
  RadialBarChart,
  ResponsiveContainer,
} from "recharts";

interface UsageRingProps {
  readonly used: number;
  readonly allowance: number | null;
  readonly unlimited: boolean;
  readonly label: string;
  readonly unit?: string;
}

const RING_COLORS = {
  used: "#4f46e5",
  remaining: "#e0e7ff",
};

function UsageRing({
  used,
  allowance,
  unlimited,
  label,
  unit = "",
}: UsageRingProps) {
  const percentage =
    unlimited || allowance === null || allowance === 0
      ? 0
      : Math.min((used / allowance) * 100, 100);

  const data = [{ value: percentage, fill: RING_COLORS.used }];

  return (
    <div className="flex flex-col items-center gap-1 w-28">
      <div className="relative w-24 h-24">
        <ResponsiveContainer width="100%" height="100%">
          <RadialBarChart
            cx="50%"
            cy="50%"
            innerRadius="60%"
            outerRadius="90%"
            startAngle={90}
            endAngle={-270}
            data={data}
          >
            <PolarAngleAxis type="number" domain={[0, 100]} tick={false} />
            <RadialBar
              background={{ fill: RING_COLORS.remaining }}
              dataKey="value"
              cornerRadius={4}
            />
          </RadialBarChart>
        </ResponsiveContainer>
        <div className="absolute inset-0 flex items-center justify-center">
          <span className="text-sm font-semibold text-neutral-700">
            {unlimited ? "∞" : `${Math.round(percentage)}%`}
          </span>
        </div>
      </div>
      <p className="text-xs font-medium text-neutral-600 text-center">
        {label}
      </p>
      {unlimited ? (
        <p className="text-xs text-indigo-600 font-medium">Unlimited</p>
      ) : (
        <p className="text-xs text-neutral-500 text-center">
          {used.toFixed(1)} / {allowance?.toFixed(0) ?? "?"} {unit}
        </p>
      )}
    </div>
  );
}

export { UsageRing };
export type { UsageRingProps };
