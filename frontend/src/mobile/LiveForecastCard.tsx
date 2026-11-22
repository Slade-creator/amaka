import { useCallback, useEffect, useMemo, useState } from "react";
import { Area, CartesianGrid, ComposedChart, Line, ReferenceLine, ResponsiveContainer, XAxis, YAxis } from "recharts";
import { BrainCircuit, Hourglass } from "lucide-react";
import { fmtAxisTick, fmtInt, fmtStamp, parseTs } from "../lib/format";
import { readinessName } from "../lib/vocabulary";
import { liveApi, NotEnoughHistory, type LiveForecast } from "../lib/liveApi";
import { Card, EmptyState, ErrorState, Segmented, Skeleton, Stat } from "./ui";
import { POLL_MS } from "../config/app";

/**
 * Live 48-hour forecast for one site, made by the trained v2 models from the
 * readings that meter kits / SCADA connectors send in. The readiness level is
 * an operator input: the model cannot see orders, so it is told.
 */
export default function LiveForecastCard({ siteId, refreshKey }: { siteId: string; refreshKey: number }) {
  const [readiness, setReadiness] = useState(4);
  const [data, setData] = useState<LiveForecast | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [waiting, setWaiting] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);

  const load = useCallback(async () => {
    setLoading(true);
    try {
      setData(await liveApi.forecast(siteId, readiness));
      setError(null);
      setWaiting(null);
    } catch (e) {
      setData(null);
      if (e instanceof NotEnoughHistory) setWaiting(e.message);
      else setError(e instanceof Error ? e.message : "Forecast failed");
    } finally {
      setLoading(false);
    }
  }, [siteId, readiness]);

  useEffect(() => {
    void load();
    const id = window.setInterval(() => void load(), POLL_MS.liveForecast);
    return () => window.clearInterval(id);
  }, [load, refreshKey]);

  const series = useMemo(() => {
    if (!data) return [];
    const rows: Array<{ t: number; actual?: number; kw?: number; lower?: number; band?: number }> = data.recent.map(
      (r) => ({ t: parseTs(r.t), actual: r.kw }),
    );
    for (const p of data.points) {
      rows.push({ t: parseTs(p.t), kw: p.kw, lower: p.lower, band: Math.max(0, p.upper - p.lower) });
    }
    return rows;
  }, [data]);

  const threshold = data?.site.threshold_kw ?? 0;
  const over = data?.peak_24h.over_by_kw != null && data.peak_24h.over_by_kw > 0;
  const originT = data ? parseTs(data.origin) : 0;

  return (
    <Card title={<><BrainCircuit size={16} aria-hidden="true" /> Live forecast · next 48 h</>} flush>
      <div className="ds-picker">
        <span className="lf-label">Readiness</span>
        <Segmented<number>
          label="Readiness level"
          value={readiness}
          onChange={setReadiness}
          options={[1, 2, 3, 4].map((r) => ({ value: r, label: `R${r}` }))}
        />
      </div>
      <p className="m-fine lf-pad">
        R{readiness} {readinessName(readiness)} — set the readiness ordered for the next two days; the model cannot
        see orders.
      </p>

      {waiting ? (
        <EmptyState icon={<Hourglass size={24} aria-hidden="true" />} title="Collecting history" body={waiting} />
      ) : error ? (
        <ErrorState message={error} onRetry={() => void load()} />
      ) : !data || loading && !data ? (
        <div className="ds-pad">
          <Skeleton h={220} />
        </div>
      ) : (
        <>
          <div className="m-kpis is-three lf-pad">
            <Stat
              label="Next 24 h peak"
              value={fmtInt(data.peak_24h.kw)}
              unit="kW"
              tone={over ? "critical" : "good"}
              note={
                threshold
                  ? over
                    ? `${fmtInt(data.peak_24h.over_by_kw)} kW over threshold`
                    : `${fmtInt(-(data.peak_24h.over_by_kw ?? 0))} kW headroom`
                  : undefined
              }
            />
            <Stat label="Peak at" value={fmtStamp(data.peak_24h.at).slice(-5)} note={fmtStamp(data.peak_24h.at).slice(0, 6)} />
            <Stat
              label="Live H1 error"
              value={data.backtest_h1.mape_pct != null ? `${data.backtest_h1.mape_pct.toFixed(1)}%` : "—"}
              note={data.backtest_h1.mae_kw != null ? `MAE ${fmtInt(data.backtest_h1.mae_kw)} kW · ${data.backtest_h1.n} h` : "needs 24 h"}
            />
          </div>
          <div className="ds-chart lf-chart">
            <ResponsiveContainer width="100%" height="100%">
              <ComposedChart data={series} margin={{ top: 8, right: 8, bottom: 0, left: -8 }}>
                <CartesianGrid stroke="rgb(var(--white-rgb)/0.06)" vertical={false} />
                <XAxis
                  dataKey="t"
                  type="number"
                  scale="time"
                  domain={["dataMin", "dataMax"]}
                  tickFormatter={(t: number) => fmtAxisTick(t, 96)}
                  tick={{ fill: "var(--dim)", fontSize: 10, fontFamily: "JetBrains Mono" }}
                  tickLine={false}
                  minTickGap={36}
                />
                <YAxis
                  tickFormatter={(v: number) => (v >= 1000 ? `${(v / 1000).toFixed(1)}k` : String(v))}
                  tick={{ fill: "var(--dim)", fontSize: 10, fontFamily: "JetBrains Mono" }}
                  tickLine={false}
                  axisLine={false}
                  width={40}
                />
                <Area dataKey="lower" stackId="b" stroke="none" fill="transparent" isAnimationActive={false} />
                <Area dataKey="band" stackId="b" stroke="none" fill="rgb(var(--accent-rgb)/0.16)" isAnimationActive={false} />
                {threshold > 0 ? <ReferenceLine y={threshold} stroke="var(--warn)" strokeDasharray="5 4" /> : null}
                <ReferenceLine x={originT} stroke="var(--teal)" strokeDasharray="2 3" />
                <Line dataKey="actual" stroke="var(--fg)" strokeWidth={1.6} dot={false} isAnimationActive={false} />
                <Line dataKey="kw" stroke="var(--accent)" strokeWidth={1.8} strokeDasharray="4 3" dot={false} isAnimationActive={false} />
              </ComposedChart>
            </ResponsiveContainer>
          </div>
          <div className="m-trace-legend">
            <span>
              <i className="m-key is-actual" /> Measured
            </span>
            <span>
              <i className="m-key is-forecast" /> Forecast
            </span>
            <span>
              <i className="m-key is-band" /> 95% range
            </span>
            <span>
              <i className="m-key is-threshold" /> Peak threshold
            </span>
          </div>
          <dl className="m-dl lf-pad lf-meta">
            <dt>Model</dt>
            <dd>{data.model.name}</dd>
            <dt>Weather</dt>
            <dd>{data.weather_source === "open-meteo" ? "Live forecast (Open-Meteo)" : data.weather_source}</dd>
            <dt>History used</dt>
            <dd className="num">{data.history_hours} h</dd>
            <dt>Updated</dt>
            <dd className="num">{fmtStamp(data.generated_at)}</dd>
          </dl>
          {data.model.note || data.notes.length ? (
            <ul className="lf-notes">
              {data.model.note ? <li>{data.model.note}</li> : null}
              {data.notes.map((n) => (
                <li key={n}>{n.charAt(0).toUpperCase() + n.slice(1)}.</li>
              ))}
            </ul>
          ) : null}
        </>
      )}
    </Card>
  );
}
