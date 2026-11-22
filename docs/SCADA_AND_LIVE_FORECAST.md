# SCADA integration and live forecasting

AMAKA takes live load from three kinds of source and runs the trained v2
models on it:

| Source | How it reaches AMAKA | Code |
|---|---|---|
| Portable meter kit | Clamp-on CT meter → gateway → HTTPS | `scripts/device_sim.py` (simulator) |
| **Site SCADA / BMS** | **OPC UA → AMAKA connector → HTTPS** | **`scripts/scada_connector.py`** |
| Historic meter data | CSV upload in the app | More → Data sources → Upload CSV |

All three post to the same ingest API (`backend/ingest_api.py`), get the same
data-quality flags, and feed the same live forecast.

```
 Site network                                         AMAKA server
┌───────────────────────────┐                ┌─────────────────────────────────┐
│ SCADA / BMS server        │                │ /api/ingest  (device token)     │
│  OPC UA endpoint          │  OPC UA        │   └─ readings store (SQLite)    │
│   ns=2;s=<site>.ActivePower_kW ◄───────────┤ quality flags · hourly rollup   │
│                           │  read-only     │                                 │
│ AMAKA connector ──────────┼──── HTTPS ────►│ live_forecast.py                │
│  (small PC / VM)          │  batches,      │   trained XGBoost + HGB models  │
│  buffer on disk           │  store & fwd   │   + Open-Meteo weather          │
└───────────────────────────┘                │   + readiness from operator     │
                                             │ /api/live/sites/{id}/forecast ──┼──► app
                                             └─────────────────────────────────┘
```

## Why OPC UA

OPC UA (IEC 62541) is the vendor-neutral standard that modern SCADA and
building-management systems expose for reading live values, and it has
security built in (signed and encrypted sessions, certificate trust, user
accounts). Reading from it means AMAKA does not depend on any one SCADA
vendor. Older plant that only speaks Modbus TCP or DNP3, or a SCADA historian
that can only export files, would need a different `read_kw()` in the
connector; enrolment, buffering, quality flags and forecasting stay the same.

## The connector

`scripts/scada_connector.py` runs on a small machine inside the site network:

1. **Enrolment.** An analyst issues a one-time code (or QR) in the app
   (More → Data sources → Add meter kit). The connector enrols once with it and
   stores its device token. The SCADA feed then appears in the app as a data
   source like a meter kit, labelled "SCADA connector | OPC UA client".
2. **Reading.** It reads the site's active-power tag every `--interval`
   seconds (minimum 5 s) and the optional quality tag.
3. **Forwarding.** It posts batches to `/api/ingest` every `--send-every`
   seconds. If AMAKA is unreachable it buffers to disk and re-sends in order
   later (the server drops duplicates). If the OPC UA link drops, it reconnects
   every 10 s.

**Security.**
- **Read-only.** The connector never writes to the SCADA system; use a
  dedicated read-only OPC UA account on the plant side.
- **Encrypted sessions.** Use `--security "Basic256Sha256,SignAndEncrypt,cert,key"`
  so sessions are signed and encrypted.
- **Passwords.** The OPC UA password is read from an environment variable,
  never from the command line.
- **Outbound only.** The only traffic leaving the site network is outbound
  HTTPS to AMAKA.

**Demo.** Install the library with `pip install "asyncua>=1.1,<2"`, then:

```powershell
# 1. Simulated SCADA server for one or more sites
python scripts/scada_opcua_sim.py --site makeni --base-kw 1100

# 2. Issue a code in the app, then start the connector
python scripts/scada_connector.py --server http://127.0.0.1:8000 `
  --opcua opc.tcp://127.0.0.1:4840/amaka/ --node "ns=2;s=makeni.ActivePower_kW" `
  --code <CODE> --device-id scada-makeni --interval 5
```

`--fault flatline` on the simulator makes its first site's meter stick, which
shows up as quality flags in the app.

## Live forecasting with the trained model

`backend/live_forecast.py` serves `GET /api/live/sites/{site}/forecast?readiness=1..4`
to any signed-in user. The app shows it on the Data sources screen
("Live forecast · next 48 h").

**Inputs, built exactly as in training (`src/v2_horizons.py`):**

| Feature group | Live source |
|---|---|
| Load history: lags 1, 2, 24 and 168 h; 24 h rolling mean and std | Hourly means of the ingested readings |
| Calendar: hour, day of week and month (sin/cos), Zambian public holidays, weekend | Computed for the target hour (Africa/Lusaka) |
| Weather: temperature, humidity, precipitation, cloud, solar radiation, wind | Open-Meteo forecast for the site; falls back to the site's 2024–25 climatology if offline |
| Readiness (R1–R4) and planned maintenance | Set by the operator in the app; the model cannot see orders |

**Model.**
- **Stage 1** is the site's XGBoost model for the horizon.
- **Stage 2** adds the HGB residual correction with its fitted weight wherever
  validation selected HGB.
- **LSTM sites:** where validation selected the LSTM residual, only Stage 1 is
  served live. The LSTM needs a full 168-hour scaled input sequence that a newly
  connected source cannot provide. The app shows which model was used.
- **New sites:** sites added in the field borrow the models of the fleet site
  with the closest peak threshold, and the app says so.

**Output.**
- **48-hour curve.** Each hour ahead uses the shortest trained horizon that
  covers it (H1, H6, H24, H48). Only hours 1, 6, 24 and 48 are exact
  direct-horizon forecasts; the rest are flagged `exact: false`.
- **95% range** from each model's test-period error band.
- **Peak.** The next-24-hour peak against the site's peak threshold.
- **Live H1 accuracy.** A rolling backtest over the last 24 measured hours: what
  the model would have forecast one hour ahead, compared with what was measured.

**Data rules.**
- **Minimum history.** At least 48 hours of good readings are needed (the
  endpoint returns HTTP 409 until then).
- **Gaps.** Gaps up to 6 hours are interpolated, as in training. Longer gaps are
  filled from the same hour a day earlier, and the response notes it.
- **Faults.** Hours flagged flatline or zero are excluded as meter faults.
- **Short history.** With less than 7 days of history, the 168-hour lag is
  approximated by the 24-hour lag, and the response notes it.
- **Current hour.** The hour still in progress is forecast, not used as history.

**Limitations to state in the report.**
- **Synthetic training data.** The models were trained on synthetic site load,
  so accuracy on real plant data will differ until they are retrained on it.
  The live H1 backtest is the honest measure to report.
- **No retraining loop yet.** Ingested data is stored, so periodic retraining is
  the natural next step.
- **Readiness is manual.** It is an operator input, not something the system
  detects.
