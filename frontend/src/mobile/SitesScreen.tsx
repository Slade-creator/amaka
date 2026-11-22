import { useMemo, useState } from "react";
import { Search, X } from "lucide-react";
import type { ScreenProps } from "./MobileApp";
import { sortByRisk } from "./FleetScreen";
import { HorizonChip, SiteRow } from "./parts";
import { EmptyState, ErrorState, ScrollView, Segmented, Skeleton } from "./ui";

type Filter = "all" | "risk" | "ok";

/** Every site, grouped by city, with search and a risk filter. */
export default function SitesScreen({ fleet, horizon, onOpenSite, onRefresh, onHorizonPress }: ScreenProps) {
  const [query, setQuery] = useState("");
  const [filter, setFilter] = useState<Filter>("all");

  const groups = useMemo(() => {
    const q = query.trim().toLowerCase();
    const sites = sortByRisk(fleet.data?.sites ?? []).filter((s) => {
      if (filter === "risk" && s.status === "nominal") return false;
      if (filter === "ok" && s.status !== "nominal") return false;
      if (!q) return true;
      return `${s.label} ${s.location} ${s.type}`.toLowerCase().includes(q);
    });
    const byCity = new Map<string, typeof sites>();
    for (const s of sites) {
      const list = byCity.get(s.location) ?? [];
      list.push(s);
      byCity.set(s.location, list);
    }
    return [...byCity.entries()].sort((a, b) => a[0].localeCompare(b[0]));
  }, [fleet.data, query, filter]);

  const risk = (fleet.data?.sites ?? []).filter((s) => s.status !== "nominal").length;
  const total = fleet.data?.sites.length ?? 0;

  return (
    <div className="m-screen">
      <header className="m-hero">
        <div className="m-hero-row">
          <div>
            <p className="m-eyebrow">{total} SITES</p>
            <h1 className="m-hero-title">Sites</h1>
          </div>
          <HorizonChip horizon={horizon} onPress={onHorizonPress} />
        </div>
        <div className="m-hero-tools">
          <label className="m-search">
            <Search size={17} aria-hidden="true" />
            <input
              type="search"
              placeholder="Search sites, cities, types"
              value={query}
              onChange={(e) => setQuery(e.target.value)}
              aria-label="Search sites"
              enterKeyHint="search"
            />
            {query ? (
              <button type="button" onClick={() => setQuery("")} aria-label="Clear search">
                <X size={16} aria-hidden="true" />
              </button>
            ) : null}
          </label>
          <Segmented<Filter>
            label="Filter"
            stretch
            value={filter}
            onChange={setFilter}
            options={[
              { value: "all", label: "All" },
              { value: "risk", label: "At risk", badge: risk },
              { value: "ok", label: "Nominal" },
            ]}
          />
        </div>
      </header>

      <ScrollView onRefresh={onRefresh}>
        {fleet.error && !fleet.data ? (
          <ErrorState message={fleet.error} onRetry={() => void onRefresh()} />
        ) : !fleet.data ? (
          <div className="m-stack">
            <Skeleton h={68} />
            <Skeleton h={68} />
            <Skeleton h={68} />
          </div>
        ) : groups.length === 0 ? (
          <EmptyState icon={<Search size={26} aria-hidden="true" />} title="No matching sites" body="Try another name or clear the filter." />
        ) : (
          <div className="m-stack">
            {groups.map(([city, sites]) => (
              <section key={city} className="m-group">
                <h2 className="m-group-title">
                  {city} <span>{sites.length}</span>
                </h2>
                <ul className="m-list m-card">
                  {sites.map((s) => (
                    <SiteRow key={s.id} site={s} onPress={() => onOpenSite(s.id)} />
                  ))}
                </ul>
              </section>
            ))}
          </div>
        )}
      </ScrollView>
    </div>
  );
}
