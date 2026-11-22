# Live data ingestion — portable plug-and-play meter kits

The research pipeline (`src/v2_*.py`) trains on synthetic load and the
dashboard replays its July–December 2025 test-period forecasts from CSV files.
This document describes the **live path**: how a real site's load reaches the
system, so a new barracks can be connected in minutes without rewiring or IT
work on site.

Code: [`backend/ingest.py`](../backend/ingest.py) (storage, enrolment, quality
rules), [`backend/ingest_api.py`](../backend/ingest_api.py) (HTTP routes),
[`scripts/device_sim.py`](../scripts/device_sim.py) (kit simulator),
[`tests/smoke_ingest.py`](../tests/smoke_ingest.py) (end-to-end test).

## 1. The portable kit

| Part | Purpose |
|---|---|
| Clamp-on 3-phase energy meter with split-core CTs | Clips around the incoming feeder cables — no cut-over, no outage, installed by the site electrician in ~20 min. Reports kW, kWh, voltage and power factor over Modbus RS485. |
| Gateway (Raspberry Pi or ESP32) | Polls the meter every 60 s, timestamps readings from its NTP/GPS clock, buffers locally, uploads over HTTPS. |
| 4G modem or site Wi-Fi | Uplink. Military sites often have patchy links, so the gateway is designed to work offline. |
| Weatherproof box + QR label | The QR carries the kit's device id. |

The kit is the same for every site; nothing site-specific is configured on it.

## 2. Plug-and-play enrolment

```
 Analyst (app)                      API                          Meter kit
 ─────────────                      ───                          ─────────
 Add site (profile)  ──POST /api/live/sites──▶  site stored
 Add meter kit       ──POST /api/devices/enrolment──▶ one-time code  (QR on screen)
                                                    ◀──POST /api/devices/enroll── scans code
                                     device token ──────────────────▶ saved on kit
                                                    ◀──POST /api/ingest (batches)──
 Data sources view   ◀──GET /api/devices, /api/live/sites/{id}/hourly──
```

1. **Add the site** (if it is not already a fleet site): name, city, type,
   coordinates, peak threshold, and optionally headcount, floor area and PV
   size. Coordinates are checked against Zambia's bounding box (this catches
   swapped lat/lon).
2. **Issue an enrolment code**: one-time, 8 characters (`K7Q4-M2XP`, no
   look-alike characters), valid for 24 h, shown as a QR code
   (`amaka://enroll?code=…&site=…`).
3. **The kit enrols** with the code and its hardware id and receives a
   **device token** bound to that one site. The code is then spent; bad
   codes are rate limited (5 per 5 minutes per address).
4. **The kit streams readings.** Weather for the site's coordinates comes from
   Open-Meteo automatically, so the kit only measures electricity.

## 3. Readings and offline buffering

`POST /api/ingest` with `Authorization: Bearer <device token>`:

```json
{"readings": [
  {"ts": "2026-11-21T08:00:00Z", "kw": 1834.2, "voltage_v": 401.3, "pf": 0.94},
  {"ts": "2026-11-21T08:01:00Z", "kw": 1840.9}
]}
```

| Rule | Behaviour |
|---|---|
| Batch size | up to 5,000 readings |
| Timestamps | ISO-8601 with offset, or epoch seconds; no offset = Zambian local time (CAT, UTC+2, no DST) |
| Clock check | more than 5 min in the future → rejected (bad gateway clock) |
| Backlog | up to 400 days old accepted |
| Range | 0–50,000 kW; power factor −1…1 |
| Duplicates | same kit + same timestamp → ignored, so a backlog can be re-sent safely |
| Response | `accepted`, `duplicates`, `rejected` and the first 20 row errors |

**Store-and-forward:** when the link is down the gateway appends readings to a
local buffer file and, once the link is back, uploads the backlog in order
before the new reading. Because the server deduplicates, a gateway that crashes
mid-upload just sends everything again.

## 4. Data quality for the analyst

`GET /api/devices` reports each kit's health:

| Status | Meaning |
|---|---|
| `waiting` | enrolled, nothing received yet |
| `online` | last reading within 3 intervals (+2 min) |
| `stale` | silent for up to an hour |
| `offline` | silent for more than an hour |
| `revoked` | token withdrawn by an analyst |
| `manual` | CSV uploads for that site |

…plus last reading time and kW, total readings and 24-hour coverage %.

`GET /api/live/sites/{site}/hourly?hours=168` rolls readings up to hourly
mean and peak kW and flags every hour:

| Flag | Rule | Typical cause |
|---|---|---|
| `gap` | no readings | link or power loss at the kit |
| `low_coverage` | < 80% of expected samples | intermittent link |
| `flatline` | ≥ 10 identical readings all hour | stuck meter, frozen Modbus register |
| `zero` | 0 kW all hour | CT clamp unplugged, breaker open |
| `spike` | hour mean > 3× the window median | CT wiring fault, meter glitch |

The response also gives completeness % and counts per flag, so the analyst can
decide whether a site's data is fit for training.

## 5. Sites without a kit — CSV upload

`POST /api/live/sites/{site}/upload` (raw CSV body, analyst only) accepts meter
exports or utility interval data. It needs a timestamp column (`timestamp`,
`time`, `datetime`, …) and a kW column (`kw`, `load_kw`, `power_kw`,
`demand_kw`, …); everything else is ignored. Uploads go through the same
validation and deduplication as kit readings.

## 6. Security

* Kits never hold a user account. Device tokens are separate, bound to one
  site, stored only as SHA-256 hashes, and can be revoked instantly
  (`DELETE /api/devices/{id}`); a revoked kit gets HTTP 401.
* Enrolment codes are single use, expire after 24 h and are stored hashed.
* Adding sites, issuing codes, uploading CSVs and revoking kits need the
  **analyst** role; every signed-in role can read live data and kit status.
* Deploy behind HTTPS (the readings reveal base activity patterns).

## 7. Storage

One SQLite file, `data/live/ingest.db` (override with `SENTINEL_INGEST_DB`):
no extra service on a demo laptop. The schema (`live_sites`, `enrol_codes`,
`devices`, `readings` keyed by kit + timestamp) maps directly onto
TimescaleDB/PostgreSQL for a multi-site deployment.

## 8. From live data to forecasts (next step)

Not built yet:

1. An hourly job builds the model inputs from live hourly load (lags 1/2/24/168 h,
   24 h rolling stats), Open-Meteo weather and the holiday calendar, then writes
   H1/H6/H24/H48 forecasts for the app.
2. **Cold start:** a new site uses the fleet-wide model with its site profile
   (headcount, floor area, PV) until it has 4–8 weeks of its own clean data,
   then gets a site-specific model, retrained monthly.
3. Hours flagged by the quality rules are excluded from training and shown as
   gaps rather than filled.

## 9. Demo with the simulator

No hardware is needed: `scripts/device_sim.py` behaves like the gateway
firmware (enrolment, saved token, back-fill, streaming, store-and-forward,
fault injection).

```powershell
# 1. Start the API, sign in as the analyst and issue an enrolment code (or use /docs)
.\run.ps1

# 2. First run: enrol, back-fill 2 days, then stream every 10 s
python scripts/device_sim.py --code K7Q4-M2XP --device-id kit-0042 --base-kw 1400 --backfill-hours 48 --interval 10

# 3. Show a link outage: buffered while offline, backlog flushed afterwards
python scripts/device_sim.py --device-id kit-0042 --interval 5 --outage-at 20 --outage-for 30

# 4. Show the data-quality flags: a stuck meter
python scripts/device_sim.py --device-id kit-0042 --fault flatline
```

The kit's token and buffer live in `.device_sim/` in the folder it was run from.

End-to-end test (starts its own server with a throwaway database):

```powershell
python tests/smoke_ingest.py
```
