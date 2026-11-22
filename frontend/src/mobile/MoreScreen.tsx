import { useState } from "react";
import { ChevronRight, Cpu, Info, LogOut, RadioTower, Server, ShieldCheck, SlidersHorizontal } from "lucide-react";
import { useSession } from "../auth/SessionContext";
import { getRoleConfig } from "../fleet/roles";
import { getApiBase } from "../lib/apiBase";
import { isNative } from "../lib/platform";
import { HORIZON_COPY, type ScreenProps } from "./MobileApp";
import { Card, ScrollView, Segmented, Sheet, tap } from "./ui";

type Props = ScreenProps & {
  linkOk: boolean;
  lastSync: Date | null;
  defaultHorizon: number;
  onDefaultHorizon: (h: number) => void;
  onOpenDataSources: () => void;
};

const ROLE_ACCESS: Record<string, string[]> = {
  commander: ["Fleet risk and cost exposure", "Site monitor, outlook and details", "PDF and CSV reports"],
  operator: [
    "Generator dispatch actions",
    "Forecast drivers (SHAP) per hour",
    "Ask questions about the chart",
    "PDF and CSV reports",
  ],
  analyst: [
    "Forecast accuracy across the fleet",
    "Forecast drivers (SHAP) per hour",
    "Ask questions about the chart",
    "PDF and CSV reports",
  ],
};

export default function MoreScreen({ overview, linkOk, lastSync, defaultHorizon, onDefaultHorizon, onRefresh, onOpenDataSources }: Props) {
  const { user, signOut } = useSession();
  const [confirm, setConfirm] = useState(false);
  const cfg = getRoleConfig(user.role);
  const initials = user.name
    .split(/\s+/)
    .map((w) => w[0])
    .join("")
    .slice(0, 2)
    .toUpperCase();
  const horizons = overview.available_horizons.length ? overview.available_horizons : [1, 6, 24, 48];

  return (
    <div className="m-screen">
      <header className="m-hero">
        <h1 className="m-hero-title">More</h1>
      </header>
      <ScrollView onRefresh={onRefresh}>
        <div className="m-stack">
          <section className="m-profile" style={{ ["--acc" as string]: cfg.accent }}>
            <span className="m-avatar" aria-hidden="true">
              {initials || "?"}
            </span>
            <div className="m-profile-text">
              <strong>{user.name}</strong>
              <span className="num">@{user.username}</span>
              <span className="m-role-badge">{cfg.label}</span>
            </div>
          </section>

          <Card title={<><ShieldCheck size={16} aria-hidden="true" /> Your access · {cfg.purpose.toLowerCase()}</>}>
            <ul className="m-ticks">
              {(ROLE_ACCESS[user.role] ?? []).map((t) => (
                <li key={t}>{t}</li>
              ))}
            </ul>
            <p className="m-fine">Roles are assigned per account by the system administrator.</p>
          </Card>

          <button type="button" className="m-card ds-entry" onClick={onOpenDataSources}>
            <RadioTower size={22} aria-hidden="true" />
            <span>
              <strong>Data sources</strong>
              <span>
                {user.role === "analyst"
                  ? "Meter kits, live readings, CSV upload"
                  : "Meter kit status (read-only)"}
              </span>
            </span>
            <ChevronRight size={18} aria-hidden="true" />
          </button>

          <Card title={<><SlidersHorizontal size={16} aria-hidden="true" /> Default forecast horizon</>}>
            <Segmented<number>
              label="Default forecast horizon"
              stretch
              value={defaultHorizon}
              onChange={onDefaultHorizon}
              options={horizons.map((h) => ({ value: h, label: `H${h}` }))}
            />
            <p className="m-fine">{HORIZON_COPY[defaultHorizon]?.desc}. Used every time the app opens.</p>
          </Card>

          <Card title={<><Server size={16} aria-hidden="true" /> Data link</>}>
            <dl className="m-dl">
              <dt>Status</dt>
              <dd className={linkOk ? "is-good" : "is-critical"}>{linkOk ? "Connected" : "Unreachable"}</dd>
              <dt>Server</dt>
              <dd className="num">{getApiBase() || window.location.origin}</dd>
              <dt>Last sync</dt>
              <dd className="num">{lastSync ? lastSync.toLocaleTimeString() : "—"}</dd>
            </dl>
            {isNative() ? (
              <p className="m-fine">To use a different server, sign out and change it on the sign-in screen.</p>
            ) : null}
          </Card>

          <Card title={<><Cpu size={16} aria-hidden="true" /> Forecast model</>}>
            <dl className="m-dl">
              <dt>Model</dt>
              <dd>{overview.model?.name}</dd>
              <dt>Horizons</dt>
              <dd className="num">{horizons.map((h) => `H${h}`).join(" · ")}</dd>
              <dt>Test period</dt>
              <dd className="num">
                {String(overview.test_period?.start).slice(0, 10)} → {String(overview.test_period?.end).slice(0, 10)}
              </dd>
              <dt>Sites</dt>
              <dd className="num">{overview.sites.length}</dd>
            </dl>
          </Card>

          <Card title={<><Info size={16} aria-hidden="true" /> About</>}>
            <p className="m-about">
              AMAKA (Bemba for “power”) forecasts electrical load for Zambian military sites and flags peak-threshold risk ahead of
              time. Load data is synthetic, driven by real weather; figures are a replay of the July–December 2025
              test period.
            </p>
            <p className="m-fine num">AMAKA Energy Command · v0.3.0 · Mulungushi University ICT431</p>
          </Card>

          <button
            type="button"
            className="m-btn is-danger is-block"
            onClick={() => {
              tap();
              setConfirm(true);
            }}
          >
            <LogOut size={18} aria-hidden="true" /> Sign out
          </button>
        </div>
      </ScrollView>

      <Sheet open={confirm} title="Sign out?" onClose={() => setConfirm(false)}>
        <p className="m-sheet-lede">You will need your username and password to sign back in.</p>
        <div className="m-sheet-actions">
          <button type="button" className="m-btn is-block" onClick={() => setConfirm(false)}>
            Cancel
          </button>
          <button type="button" className="m-btn is-danger is-block" onClick={signOut}>
            <LogOut size={18} aria-hidden="true" /> Sign out
          </button>
        </div>
      </Sheet>
    </div>
  );
}
