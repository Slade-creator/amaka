import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { Bar, CartesianGrid, ComposedChart, Line, ReferenceArea, ReferenceLine, ResponsiveContainer, XAxis, YAxis } from "recharts";
import { QRCodeSVG } from "qrcode.react";
import { Copy, Cpu, FileUp, KeyRound, Plus, RadioTower, Trash2 } from "lucide-react";
import type { Role } from "../fleet/roles";
import LiveForecastCard from "./LiveForecastCard";
import { POLL_MS } from "../config/app";
import { fmtAxisTick, fmtInt, fmtStamp, parseTs } from "../lib/format";
import { ago, liveApi, type Device, type Enrolment, type FlagKind, type Hourly, type LiveSite } from "../lib/liveApi";
import { Card, EmptyState, ErrorState, ScrollView, Segmented, Sheet, Skeleton, Spinner, Stat, TopBar, tap } from "./ui";

type Props = { role: Role; onBack: () => void };

const FLAG_LABEL: Record<FlagKind, string> = {
  gap: "Gap",
  low_coverage: "Low coverage",
  flatline: "Flatline",
  zero: "Zero reading",
  spike: "Spike",
};

const STATUS_COPY: Record<Device["status"], string> = {
  waiting: "Waiting for first reading",
  online: "Online",
  stale: "Late",
  offline: "Offline",
  revoked: "Revoked",
  manual: "Manual uploads",
};

/**
 * Live data sources: meter kits reporting real load, per-site hourly
 * completeness with quality flags, and (analysts only) kit enrolment, CSV
 * upload and revocation. Measured load only — live forecasting is not built.
 */
export default function DataSourcesScreen({ role, onBack }: Props) {
  const analyst = role === "analyst";
  const [sites, setSites] = useState<LiveSite[] | null>(null);
  const [devices, setDevices] = useState<Device[] | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [siteId, setSiteId] = useState<string>("");
  const [hours, setHours] = useState(168);
  const [hourly, setHourly] = useState<Hourly | null>(null);
  const [hourlyErr, setHourlyErr] = useState<string | null>(null);
  const [sheet, setSheet] = useState<null | "enrol" | "upload" | { revoke: Device }>(null);

  const load = useCallback(async () => {
    setError(null);
    try {
      const [s, d] = await Promise.all([liveApi.sites(), liveApi.devices()]);
      setSites(s);
      setDevices(d);
      setSiteId((prev) => prev || d.find((x) => x.status !== "revoked")?.site_id || s[0]?.id || "");
    } catch (e) {
      setError(e instanceof Error ? e.message : "Could not load data sources");
    }
  }, []);

  useEffect(() => {
    void load();
    const id = window.setInterval(() => void liveApi.devices().then(setDevices).catch(() => {}), POLL_MS.liveData);
    return () => window.clearInterval(id);
  }, [load]);

  const loadHourly = useCallback(async () => {
    if (!siteId) return;
    setHourlyErr(null);
    try {
      setHourly(await liveApi.hourly(siteId, hours));
    } catch (e) {
      setHourly(null);
      setHourlyErr(e instanceof Error ? e.message : "Could not load readings");
    }
  }, [siteId, hours]);

  useEffect(() => {
    setHourly(null);
    void loadHourly();
    // Live readings keep arriving: refresh the chart with the kit list.
    const id = window.setInterval(() => void loadHourly(), POLL_MS.liveData);
    return () => window.clearInterval(id);
  }, [loadHourly]);

  const refresh = async () => {
    await Promise.all([load(), loadHourly()]);
  };

  const active = (devices ?? []).filter((d) => d.status !== "revoked");
  const online = active.filter((d) => d.status === "online").length;
  const siteKits = (devices ?? []).filter((d) => d.site_id === siteId);

  return (
    <div className="m-push" role="region" aria-label="Data sources">
      <TopBar title="Data sources" subtitle="Live meter kits and uploads" onBack={onBack} />
      <ScrollView onRefresh={refresh}>
        {error && !devices ? (
          <ErrorState message={error} onRetry={() => void load()} />
        ) : !devices || !sites ? (
          <div className="m-stack">
            <Skeleton h={90} />
            <Skeleton h={260} />
          </div>
        ) : (
          <div className="m-stack">
            <div className="m-kpis">
              <Stat label="Kits online" value={online} unit={`/ ${active.length}`} tone={online ? "good" : undefined} />
              <Stat label="Sites" value={sites.length} note={`${sites.filter((s) => s.source === "field").length} added`} />
              <Stat
                label="24 h coverage"
                value={
                  active.length
                    ? `${Math.round(active.reduce((a, d) => a + d.coverage_24h_pct, 0) / active.length)}%`
                    : "—"
                }
              />
            </div>

            {analyst ? (
              <div className="ds-actions">
                <button type="button" className="m-btn is-active" onClick={() => setSheet("enrol")}>
                  <Plus size={17} aria-hidden="true" /> Add meter kit
                </button>
                <button type="button" className="m-btn" onClick={() => setSheet("upload")} disabled={!siteId}>
                  <FileUp size={17} aria-hidden="true" /> Upload CSV
                </button>
              </div>
            ) : (
              <p className="m-fine">Read-only view. Analysts enrol kits and upload meter data.</p>
            )}

            <Card title="Measured load" flush>
              <div className="ds-picker">
                <select value={siteId} onChange={(e) => setSiteId(e.target.value)} aria-label="Site">
                  {sites.map((s) => (
                    <option key={s.id} value={s.id}>
                      {s.label}
                      {s.source === "field" ? " (added)" : ""}
                    </option>
                  ))}
                </select>
                <Segmented<number>
                  label="Window"
                  value={hours}
                  onChange={setHours}
                  options={[
                    { value: 24, label: "24H" },
                    { value: 168, label: "7D" },
                    { value: 720, label: "30D" },
                  ]}
                />
              </div>
              {hourlyErr ? (
                <ErrorState message={hourlyErr} onRetry={() => void loadHourly()} />
              ) : !hourly ? (
                <div className="ds-pad">
                  <Skeleton h={200} />
                </div>
              ) : (
                <HourlyChart data={hourly} rangeHours={hours} />
              )}
            </Card>

            {siteId ? <LiveForecastCard siteId={siteId} refreshKey={devices.length} /> : null}

            <Card title={<><Cpu size={16} aria-hidden="true" /> Meter kits</>} flush>
              {devices.length === 0 ? (
                <EmptyState
                  icon={<RadioTower size={26} aria-hidden="true" />}
                  title="No kits yet"
                  body={analyst ? "Add a meter kit to start streaming real load." : "No meter kits are enrolled."}
                />
              ) : (
                <ul className="m-list">
                  {[...siteKits, ...devices.filter((d) => d.site_id !== siteId)].map((d) => (
                    <li key={d.id}>
                      <div className={`ds-kit is-${d.status}`}>
                        <span className={`ds-dot is-${d.status}`} aria-hidden="true" />
                        <button type="button" className="ds-kit-main" onClick={() => setSiteId(d.site_id)}>
                          <strong>{d.label || d.id}</strong>
                          <span>
                            {d.site_label} · {STATUS_COPY[d.status]}
                          </span>
                          <span className="num">
                            {d.status === "waiting" ? "no data yet" : `last seen ${ago(d.last_seen_age_s)}`}
                            {d.last_kw != null ? ` · ${fmtInt(d.last_kw)} kW` : ""}
                          </span>
                        </button>
                        <span className="ds-cov num">
                          {Math.round(d.coverage_24h_pct)}%<small>24 h</small>
                        </span>
                        {analyst && d.status !== "revoked" && d.status !== "manual" ? (
                          <button
                            type="button"
                            className="m-icon-btn"
                            aria-label={`Revoke ${d.label || d.id}`}
                            onClick={() => setSheet({ revoke: d })}
                          >
                            <Trash2 size={18} aria-hidden="true" />
                          </button>
                        ) : null}
                      </div>
                    </li>
                  ))}
                </ul>
              )}
            </Card>

            <p className="m-fine">
              Live data comes from meter kits, SCADA connectors (OPC UA) and CSV uploads. The live forecast runs the
              trained models on these readings; forecasts elsewhere in the app replay the 2025 test period.
            </p>
          </div>
        )}
      </ScrollView>

      {analyst ? (
        <>
          <EnrolSheet
            open={sheet === "enrol"}
            sites={sites ?? []}
            defaultSite={siteId}
            onClose={() => setSheet(null)}
            onChanged={load}
          />
          <UploadSheet
            open={sheet === "upload"}
            site={sites?.find((s) => s.id === siteId)}
            onClose={() => setSheet(null)}
            onDone={refresh}
          />
          <RevokeSheet
            device={sheet && typeof sheet === "object" ? sheet.revoke : null}
            onClose={() => setSheet(null)}
            onDone={load}
          />
        </>
      ) : null}
    </div>
  );
}

/* ------------------------------------------------------------------ */
/* hourly chart                                                        */
/* ------------------------------------------------------------------ */

function HourlyChart({ data, rangeHours }: { data: Hourly; rangeHours: number }) {
  const rows = useMemo(
    () =>
      data.rows.map((r) => ({
        t: parseTs(r.hour),
        mean: r.mean_kw,
        peak: r.peak_kw,
        // Missing hours (gap) are shaded grey; quality faults red.
        flagged: r.flags.some((f) => f !== "gap"),
        gap: r.flags.includes("gap"),
      })),
    [data],
  );
  const flagged = useMemo(() => rows.filter((r) => r.flagged), [rows]);
  const gaps = useMemo(() => rows.filter((r) => r.gap && !r.flagged), [rows]);
  const hasData = data.rows.some((r) => r.mean_kw != null);
  const threshold = data.site.threshold_kw;
  const counts = Object.entries(data.flag_counts ?? {}).filter(([, n]) => n > 0) as Array<[FlagKind, number]>;

  return (
    <div className="ds-chart-wrap">
      <div className="ds-summary">
        <Stat
          label="Completeness"
          value={`${Math.round(data.completeness_pct)}%`}
          tone={data.completeness_pct >= 95 ? "good" : data.completeness_pct >= 70 ? "warning" : "critical"}
          note={`${data.hours} h window`}
        />
        <div className="ds-flags">
          {counts.length === 0 ? (
            <span className="ds-flag is-ok">No quality flags</span>
          ) : (
            counts.map(([k, n]) => (
              <span key={k} className={`ds-flag is-${k}`}>
                {FLAG_LABEL[k]} · {n}
              </span>
            ))
          )}
        </div>
      </div>
      {!hasData ? (
        <EmptyState title="No readings in this window" body="Enrol a kit or upload a CSV for this site." />
      ) : (
        <div className="ds-chart">
          <ResponsiveContainer width="100%" height="100%">
            <ComposedChart data={rows} margin={{ top: 8, right: 8, bottom: 0, left: -8 }}>
              <CartesianGrid stroke="rgb(var(--white-rgb)/0.06)" vertical={false} />
              <XAxis
                dataKey="t"
                type="number"
                scale="time"
                domain={["dataMin", "dataMax"]}
                tickFormatter={(t: number) => fmtAxisTick(t, rangeHours)}
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
              {gaps.map((r) => (
                <ReferenceArea
                  key={`g${r.t}`}
                  x1={r.t - 1_800_000}
                  x2={r.t + 1_800_000}
                  fill="var(--dim)"
                  fillOpacity={0.08}
                  strokeOpacity={0}
                />
              ))}
              {flagged.map((r) => (
                <ReferenceArea
                  key={r.t}
                  x1={r.t - 1_800_000}
                  x2={r.t + 1_800_000}
                  fill="var(--crit)"
                  fillOpacity={0.14}
                  strokeOpacity={0}
                />
              ))}
              {threshold > 0 ? <ReferenceLine y={threshold} stroke="var(--warn)" strokeDasharray="5 4" /> : null}
              <Bar dataKey="peak" fill="rgb(var(--accent-rgb)/0.18)" isAnimationActive={false} />
              <Line dataKey="mean" stroke="var(--fg)" strokeWidth={1.6} dot={false} connectNulls={false} isAnimationActive={false} />
            </ComposedChart>
          </ResponsiveContainer>
        </div>
      )}
      <div className="m-trace-legend">
        <span>
          <i className="m-key is-actual" /> Hourly mean
        </span>
        <span>
          <i className="m-key is-band" /> Hourly peak
        </span>
        <span>
          <i className="m-key is-threshold" /> Peak threshold
        </span>
        <span>
          <i className="ds-key-flag" /> Quality flag
        </span>
        <span>
          <i className="ds-key-flag is-gap" /> No data
        </span>
      </div>
    </div>
  );
}

/* ------------------------------------------------------------------ */
/* enrol                                                               */
/* ------------------------------------------------------------------ */

const ID_RE = /^[a-z][a-z0-9_]*$/;

function EnrolSheet({
  open,
  sites,
  defaultSite,
  onClose,
  onChanged,
}: {
  open: boolean;
  sites: LiveSite[];
  defaultSite: string;
  onClose: () => void;
  onChanged: () => Promise<void>;
}) {
  const [mode, setMode] = useState<"existing" | "new">("existing");
  const [siteId, setSiteId] = useState(defaultSite);
  const [label, setLabel] = useState("");
  const [form, setForm] = useState({ id: "", label: "", location: "", type: "Barracks", lat: "", lon: "", threshold_kw: "" });
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState<string | null>(null);
  const [code, setCode] = useState<Enrolment | null>(null);
  const [copied, setCopied] = useState(false);

  // Reset only when the sheet opens — the site list refreshes after a code is
  // issued, and that must not wipe the code off the screen.
  useEffect(() => {
    if (open) {
      setSiteId(defaultSite || sites[0]?.id || "");
      setCode(null);
      setErr(null);
      setLabel("");
      setCopied(false);
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [open]);

  const submit = async () => {
    setErr(null);
    let target = siteId;
    if (mode === "new") {
      const lat = Number(form.lat);
      const lon = Number(form.lon);
      const thr = Number(form.threshold_kw);
      if (!ID_RE.test(form.id)) return setErr("Site ID: lowercase letters, digits and _, starting with a letter.");
      if (!form.label.trim() || !form.location.trim()) return setErr("Enter the site name and location.");
      if (!Number.isFinite(lat) || !Number.isFinite(lon)) return setErr("Enter latitude and longitude as numbers.");
      if (!(thr > 0)) return setErr("Enter the peak threshold in kW.");
      setBusy(true);
      try {
        const s = await liveApi.addSite({
          id: form.id,
          label: form.label.trim(),
          location: form.location.trim(),
          type: form.type.trim() || "Barracks",
          lat,
          lon,
          threshold_kw: thr,
        });
        target = s.id;
      } catch (e) {
        setBusy(false);
        return setErr(e instanceof Error ? e.message : "Could not add the site");
      }
    }
    if (!target) return setErr("Choose a site.");
    setBusy(true);
    try {
      tap("medium");
      setCode(await liveApi.enrol(target, label.trim()));
      await onChanged();
    } catch (e) {
      setErr(e instanceof Error ? e.message : "Could not create a code");
    } finally {
      setBusy(false);
    }
  };

  const copy = async () => {
    if (!code) return;
    try {
      await navigator.clipboard.writeText(code.code);
      setCopied(true);
    } catch {
      setCopied(false);
    }
  };

  const field = (k: keyof typeof form, lbl: string, mode?: "decimal" | "text") => (
    <label className="ds-field">
      <span>{lbl}</span>
      <input
        value={form[k]}
        inputMode={mode === "decimal" ? "decimal" : "text"}
        autoCapitalize="none"
        onChange={(e) => setForm((f) => ({ ...f, [k]: e.target.value }))}
      />
    </label>
  );

  return (
    <Sheet open={open} title={code ? "Enrolment code" : "Add meter kit"} onClose={onClose}>
      {code ? (
        <div className="ds-code-wrap">
          <p className="m-sheet-lede">
            Enter this code on the kit for <b>{sites.find((s) => s.id === code.site_id)?.label ?? code.site_id}</b>. It
            works once and is shown only now.
          </p>
          <div className="ds-qr" aria-hidden="true">
            <QRCodeSVG value={code.qr_payload} size={196} level="M" marginSize={2} bgColor="var(--white)" fgColor="var(--bg)" />
          </div>
          <p className="m-fine ds-qr-hint">Scan with the kit, or type the code:</p>
          <div className="ds-code num" aria-label={`Enrolment code ${code.code}`}>
            {code.code}
          </div>
          <p className="m-fine num">Expires {fmtStamp(code.expires_at)}</p>
          <button type="button" className="m-btn is-block" onClick={copy}>
            <Copy size={16} aria-hidden="true" /> {copied ? "Copied" : "Copy code"}
          </button>
          <button type="button" className="m-btn is-active is-block" onClick={onClose}>
            Done
          </button>
        </div>
      ) : (
        <div className="ds-form">
          <Segmented<"existing" | "new">
            label="Site"
            stretch
            value={mode}
            onChange={setMode}
            options={[
              { value: "existing", label: "Existing site" },
              { value: "new", label: "New site" },
            ]}
          />
          {mode === "existing" ? (
            <label className="ds-field">
              <span>Site</span>
              <select value={siteId} onChange={(e) => setSiteId(e.target.value)}>
                {sites.map((s) => (
                  <option key={s.id} value={s.id}>
                    {s.label}
                  </option>
                ))}
              </select>
            </label>
          ) : (
            <>
              {field("label", "Site name")}
              {field("id", "Site ID (e.g. lusaka_depot)")}
              {field("location", "Town")}
              {field("type", "Type")}
              <div className="ds-row">
                {field("lat", "Latitude", "decimal")}
                {field("lon", "Longitude", "decimal")}
              </div>
              {field("threshold_kw", "Peak threshold (kW)", "decimal")}
            </>
          )}
          <label className="ds-field">
            <span>Kit name (optional)</span>
            <input value={label} onChange={(e) => setLabel(e.target.value)} placeholder="Main incomer" />
          </label>
          {err ? <p className="m-sheet-msg is-error">{err}</p> : null}
          <button type="button" className="m-btn is-active is-block" onClick={() => void submit()} disabled={busy}>
            {busy ? <Spinner /> : <KeyRound size={17} aria-hidden="true" />} Create enrolment code
          </button>
        </div>
      )}
    </Sheet>
  );
}

/* ------------------------------------------------------------------ */
/* upload                                                              */
/* ------------------------------------------------------------------ */

function UploadSheet({
  open,
  site,
  onClose,
  onDone,
}: {
  open: boolean;
  site?: LiveSite;
  onClose: () => void;
  onDone: () => Promise<void>;
}) {
  const input = useRef<HTMLInputElement | null>(null);
  const [busy, setBusy] = useState(false);
  const [msg, setMsg] = useState<{ ok: boolean; text: string; errors?: string[] } | null>(null);

  useEffect(() => {
    if (open) setMsg(null);
  }, [open]);

  const pick = async (file: File | undefined) => {
    if (!file || !site) return;
    if (file.size > 10 * 1024 * 1024) return setMsg({ ok: false, text: "File is larger than 10 MB." });
    setBusy(true);
    setMsg(null);
    try {
      const r = await liveApi.upload(site.id, await file.text());
      setMsg({
        ok: r.accepted > 0,
        text: `${fmtInt(r.accepted)} accepted · ${fmtInt(r.duplicates)} duplicates · ${fmtInt(r.rejected)} rejected`,
        errors: r.errors.slice(0, 5).map((e) => `Row ${e.index + 1}: ${e.error}`),
      });
      await onDone();
    } catch (e) {
      setMsg({ ok: false, text: e instanceof Error ? e.message : "Upload failed" });
    } finally {
      setBusy(false);
      if (input.current) input.current.value = "";
    }
  };

  return (
    <Sheet open={open} title="Upload meter CSV" onClose={onClose}>
      <p className="m-sheet-lede">
        Readings for <b>{site?.label ?? "—"}</b>. The file needs a timestamp column and a kW column; repeated
        readings are skipped.
      </p>
      <input
        ref={input}
        type="file"
        accept=".csv,text/csv"
        hidden
        onChange={(e) => void pick(e.target.files?.[0])}
      />
      <button type="button" className="m-btn is-active is-block" onClick={() => input.current?.click()} disabled={busy}>
        {busy ? <Spinner /> : <FileUp size={17} aria-hidden="true" />} Choose CSV file
      </button>
      {msg ? (
        <div className={`m-sheet-msg${msg.ok ? " is-ok" : " is-error"}`}>
          {msg.text}
          {msg.errors?.length ? (
            <ul className="ds-errs">
              {msg.errors.map((e) => (
                <li key={e}>{e}</li>
              ))}
            </ul>
          ) : null}
        </div>
      ) : null}
    </Sheet>
  );
}

/* ------------------------------------------------------------------ */
/* revoke                                                              */
/* ------------------------------------------------------------------ */

function RevokeSheet({
  device,
  onClose,
  onDone,
}: {
  device: Device | null;
  onClose: () => void;
  onDone: () => Promise<void>;
}) {
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState<string | null>(null);
  useEffect(() => setErr(null), [device]);
  const go = async () => {
    if (!device) return;
    setBusy(true);
    try {
      tap("medium");
      await liveApi.revoke(device.id);
      await onDone();
      onClose();
    } catch (e) {
      setErr(e instanceof Error ? e.message : "Could not revoke");
    } finally {
      setBusy(false);
    }
  };
  return (
    <Sheet open={device !== null} title="Revoke meter kit?" onClose={onClose}>
      <p className="m-sheet-lede">
        <b>{device?.label || device?.id}</b> at {device?.site_label} is locked out immediately and its readings stop.
        Readings already received are kept. To use the kit again, enrol it with a new code.
      </p>
      {err ? <p className="m-sheet-msg is-error">{err}</p> : null}
      <div className="m-sheet-actions">
        <button type="button" className="m-btn is-block" onClick={onClose}>
          Cancel
        </button>
        <button type="button" className="m-btn is-danger is-block" onClick={() => void go()} disabled={busy}>
          {busy ? <Spinner /> : <Trash2 size={17} aria-hidden="true" />} Revoke
        </button>
      </div>
    </Sheet>
  );
}
