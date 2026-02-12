# MAESTRO Observability Blueprint

## Obiettivo

Evolvere `agent-dashboard` da vista stato-card a **control room realtime** per OpenClaw:

- Cosa stanno facendo ora gli agenti (live)
- Cosa hanno appena fatto (timeline affidabile)
- Cosa faranno dopo (next action predittiva)
- Con chi stanno interagendo (grafo relazioni)
- Quali cron sono imminenti/in ritardo/falliti
- Quali subprocessi sono attivi, zombie, bloccati
- Quali lock/watchdog/stalli sono in corso

## OpenClaw Compliance estratta dalle regole

Dai documenti di governance e protocollo emerge che lo sciame è tenuto a usare alcuni canali standard (obbligatori o fortemente prescritti):

- `shared/events/bus.jsonl` come broadcast bus
- `shared/requests/` e `shared/results/` per asincrono punto-a-punto
- heartbeat periodici e lettura canali durante heartbeat
- action ledger in `shared/action-ledger/{agentId}/current.jsonl`
- configurazione principale in `~/.openclaw/openclaw.json`
- cron state in `~/.openclaw/cron/jobs.json` e `~/.openclaw/cron/runs/*`

Nota cruciale per pubblicazione: queste convenzioni sono comuni, ma non vanno assunte come prerequisito rigido in runtime.
Il prodotto deve essere **compliant by design**, non **fragile by assumption**.

## Vincolo prodotto: nessun prerequisito hard-coded

La versione pubblicabile deve funzionare anche quando:

- alcune directory condivise non esistono ancora
- i file hanno nomi/posizioni diverse
- parte dei protocolli non è stata ancora adottata nell'installazione target
- l'istanza usa solo CLI/gateway e non espone direttamente gli stessi file

Principio: **progressive capability detection** + **graceful degradation**.

## Stato attuale (sintesi)

- Ingestion principale da `shared/events/bus.jsonl` (tail file polling)
- Bridge sessioni agenti (`agents/*/sessions/*.jsonl`) → evento sintetico su bus
- UI card-based via Socket.IO (`init`, `update`)
- Persiste mini-history message/thought per agente in `shared/events/history/*.jsonl`

## Problemi strutturali attuali

1. **Copertura dati incompleta**
   - Non ingestisce nativamente `cron/jobs.json` e `cron/runs/*.jsonl`.
   - Nessuna telemetria processi/subprocessi (PID tree, stato runtime).
   - Nessuna correlazione forte con `shared/requests/*`, `shared/results/*`, lock file.

2. **Semantica eventi fragile**
   - Session bridge fa preview testuale (truncate 240 char), perde contesto.
   - Ruoli/tool events non normalizzati in schema typed unico.
   - Duplicazione eventi/history per dedup in-memory non persistente.

3. **Realtime non deterministico**
   - Loop polling (`sleep`) su file grandi e multi-source.
   - Reader in-process: rischio multi-reader in deployment multi-worker.
   - Backfill e live non separati come stream offset-safe.

4. **Mancanza di modello relazionale**
   - Non esistono entità forti: `Turn`, `ToolCall`, `CronRun`, `Process`, `InteractionEdge`.
   - Nessun grafo “chi parla con chi / chi dipende da chi”.

## Architettura target (MAESTRO)

### 0) Discovery & Capability Layer (nuovo, obbligatorio)

Prima di avviare l'ingestion, MAESTRO effettua bootstrap dinamico:

1. Determina OpenClaw root (`OPENCLAW_HOME`, cwd, fallback su `~/.openclaw`).
2. Carica capability providers disponibili (filesystem, CLI, gateway).
3. Esegue probe non distruttivi e costruisce `capabilities.json` runtime.
4. Abilita solo i connettori supportati nell'installazione corrente.

Esempio capability model:

```json
{
  "root": "/path/openclaw",
  "providers": {
    "filesystem": true,
    "openclaw_cli": true,
    "gateway": true
  },
  "channels": {
    "event_bus": {"available": true, "source": "filesystem"},
    "requests": {"available": false, "source": null},
    "cron_jobs": {"available": true, "source": "filesystem"},
    "cron_runs": {"available": true, "source": "filesystem"},
    "action_ledger": {"available": false, "source": null}
  }
}
```

Se una capability manca, il sistema:

- non fallisce il bootstrap
- segnala "partial observability"
- propone remediation in UI (non blocca l'avvio)

### 1) Ingestion Layer (connettori)

- **Bus Connector**
  - Consuma `shared/events/bus.jsonl` con offset persistente.
  - Se assente: fallback provider CLI/gateway (event stream o polling comandi).
- **Session Connector**
  - Consuma tutte le sessioni agenti con offset per file + rotazione file-safe.
  - Supporta `user`, `assistant`, `toolCall`, `toolResult`, `thinking`.
  - Se assente: deriva turn activity da cron-runs e bus summary.
- **Cron Connector**
  - Snapshot da `cron/jobs.json` + stream da `cron/runs/*.jsonl`.
  - Se assente: fallback `openclaw cron list --json` (se disponibile).
- **Process Connector**
  - Snapshot periodico process tree (PID, PPID, cmd, cpu, rss, start, state).
  - Mapping processo → agente tramite cwd/path/config.
- **Lock/Watchdog Connector**
  - Lock files `agents/*/sessions/*.jsonl.lock` + eventi watchdog.
  - Se lock files non presenti: detector solo eventi `watchdog`/`blocker`.
- **Request/Result Connector**
  - Parsing `shared/requests/*` e `shared/results/*` per dipendenze cross-agent.
  - Se assenti: interaction graph da direct agent messages + bus causality.

### Provider abstraction (anti-fragile)

Ogni connettore implementa la stessa interfaccia:

```text
discover() -> capability
snapshot() -> normalized events[]
stream(since_offset) -> event iterator
health() -> connector status
```

Provider concreti:

- `FsProvider` (installazioni file-centriche)
- `CliProvider` (installazioni command-centriche)
- `GatewayProvider` (installazioni network-centriche)
- `NullProvider` (capability non disponibile, nessun crash)

### 2) Correlation Layer

- Correlatore a ID e finestre temporali:
  - `Turn` ↔ `ToolCall` ↔ `ToolResult`
  - `CronJob` ↔ `CronRun`
  - `Agent` ↔ `Process`
  - `Request` ↔ `Result`
- Deriva stati ad alto livello:
  - `doing_now`
  - `just_done`
  - `next_expected_action`
  - `blocked_by` (lock, timeout, dependency, human input)

### 3) Storage Layer

- **Hot store (real-time):** Redis Streams o NATS JetStream
  - fan-out websocket efficiente
  - replay breve (ultimi N minuti)
- **Warm store (query/timeline):** SQLite WAL o Postgres
  - timeline per agente
  - query per diagnostica e analytics
- **Cold archive:** JSONL append-only compatibile con formato attuale

### 4) Delivery Layer

- Gateway WS/SSE con canali:
  - `/stream/agents`
  - `/stream/cron`
  - `/stream/processes`
  - `/stream/graph`
  - `/stream/alerts`
- Snapshot iniziale coerente + delta events versionati (`seq`, `offset`, `source`).

## Modello dati canonico (evento unificato)

```json
{
  "id": "evt_...",
  "ts": "2026-02-12T18:12:27.316Z",
  "source": "session|bus|cron|proc|lock|request|result",
  "entity": "agent|turn|cron_job|cron_run|process|interaction|alert",
  "agent": "europa",
  "kind": "turn.started|turn.completed|cron.run.finished|process.spawned|alert.lock_stale",
  "severity": "info|warn|error",
  "labels": {"sessionId": "...", "jobId": "..."},
  "payload": {},
  "causality": {"parentId": null, "traceId": "..."},
  "dedupKey": "...",
  "seq": 123456
}
```

Estensione per compliance/portabilità:

```json
{
  "evidence": {
    "provider": "filesystem|cli|gateway",
    "confidence": "high|medium|low",
    "rawRef": "opaque pointer"
  },
  "compliance": {
    "protocol": "event-bus|request-result|heartbeat|ledger",
    "isProtocolConform": true
  }
}
```

## UI target (control room)

1. **Live Command Center**
   - Stato globale sciame (healthy/degraded/incident)
   - Throughput eventi/s e lag ingestion

2. **Agent Cockpit**
   - `Doing now` (turn corrente, tool in corso)
   - `Just done` (ultimi 3 output utili)
   - `Next` (cron imminente + prediction)
   - `Blocked by` (persona/processo/lock/dep)

3. **Cron Radar**
   - Timeline prossime 60 min
   - tardiness, failure rate, jitter
   - “missed run detector”

4. **Process Observatory**
   - Process tree per agente
   - subprocess long-running / zombie / orphan
   - CPU/Mem live + leak suspicion

5. **Interaction Graph**
   - Grafo agenti ↔ richieste ↔ risultati
   - Heatmap collaborazione e colli di bottiglia

6. **Forensic Timeline**
   - Ricostruzione causale incidenti
   - replay evento-per-evento con filtro per trace

## Performance target

- P50 ingest-to-UI < 400ms
- P95 ingest-to-UI < 1200ms
- Nessun duplicate render a parità di `dedupKey`
- CPU backend monitor < 1 core medio su carico normale
- Backfill cold start < 3s su 100k eventi (snapshot sintetico)

## Correttezza e resilienza

- Offset persistenti per ogni sorgente
- Idempotenza su `dedupKey`
- Checkpointing periodico + recovery deterministico
- Schema validation hard-fail + dead-letter queue eventi invalidi
- Contract tests tra connector e canonical schema
- Capability tests: il sistema deve avviarsi anche con 0..N canali disponibili
- Nessuna dipendenza obbligatoria su un singolo file/path

## Modalità operative (publication-ready)

### Modalità `strict-openclaw`

Usata quando l'installazione adotta tutti i protocolli canonici.

- Validazione completa protocollo (`bus`, `requests`, `results`, `ledger`, `cron`)
- KPI/alert con coverage massima

### Modalità `portable-openclaw` (default)

Usata per funzionare out-of-the-box su setup eterogenei.

- Auto-detect canali disponibili
- Fallback automatici provider-based
- UX trasparente con barra "Coverage" per sorgente/capability

### Modalità `minimal`

Requisiti minimi:

- accesso a OpenClaw root o CLI
- possibilità di leggere almeno un segnale runtime (es. cron o bus o sessions)

Con minima telemetry attiva:

- il dashboard parte comunque
- mostra insight limitati ma reali
- guida il maintainer ad abilitare capacità mancanti

### Modalità `core-only-passive` (nuova, consigliata per pubblicazione)

Questa modalità usa esclusivamente feature core OpenClaw e non richiede che gli agenti:

- scrivano file specifici
- rispettino protocolli custom locali
- modifichino il proprio comportamento

Sorgenti consentite (read-only):

- `openclaw agents list --json`
- `openclaw cron list --json`
- `openclaw status --json`
- `openclaw system presence --json`
- `openclaw health` / `openclaw doctor` (se disponibili in JSON)

Niente tail diretto di file custom come prerequisito di funzionamento.

#### Cosa ottieni in core-only-passive

- Discovery agenti e metadati runtime
- Stato scheduler cron (next run, last run, status, duration)
- Presenza nodi/gateway
- Attività recente aggregata da status/session summary (quando esposta dal core)

#### Cosa non puoi inferire con precisione assoluta (senza canali opzionali)

- contenuto dei pensieri/tool-call granulari
- causalità completa request/result cross-agent
- process tree dettagliato per ogni turn

Il dashboard deve mostrare esplicitamente **confidence levels** su questi pannelli.

## Core Signal Mapping (no agent changes)

| Insight UI | Segnale core | Strategia |
|---|---|---|
| "Chi c'è" | `agents list --json` | inventory live agenti |
| "Cosa sta per fare" | `cron list --json` + `nextRunAtMs` | previsione next action |
| "Cosa ha appena fatto" | `cron list --json` + `lastRunAtMs/status/duration` | last execution summary |
| "Sistema sano?" | `status --json`, `health`, `system presence` | health board |
| "Attività recente" | `status --json.sessions.recent` (se disponibile) | recent activity feed |

## Regola d'oro di prodotto

Prima release pubblica = `core-only-passive` by default.

Poi feature advanced (bus/requests/results/ledger/sessions raw) vengono attivate come plugin opzionali auto-rilevati.

## Sicurezza e governance

- Redazione automatica segreti (token/chat id/path sensibili)
- Policy su pensieri sensibili (`thinking`) con livelli di visibilità
- Audit trail accessi dashboard

## Piano implementativo (4 fasi)

### Fase 1 — Fondazione Telemetria (1-2 giorni)

- Introdurre schema canonical e bus interno typed
- Discovery & Capability layer
- Provider abstraction (`FsProvider`, `CliProvider`, `NullProvider`)
- Connettori: `bus`, `session`, `cron/jobs`, `cron/runs` con fallback
- Dedup persistente e offset-store locale
- Endpoint snapshot+delta unico

### Fase 2 — Processi e Diagnostica (2-3 giorni)

- Process connector con mapping PID→agent
- Lock connector + detector stalli
- Dashboard: Cron Radar + Process Observatory

### Fase 3 — Grafo e Predizione (2-4 giorni)

- Correlazione `request/result/turn`
- Interaction Graph
- Modulo `next_expected_action` (regole euristiche)

### Fase 4 — Hardening Produzione (1-2 giorni)

- Benchmark e tuning
- Alerting SLO (latency lag, duplicate spikes)
- Test caos (restart reader, file rotation, burst events)
- Test matrix installazioni: full, partial, minimal

## Checklist compliance per rilascio pubblico

- Nessun path assoluto hard-coded in codice
- Root e canali risolti via discovery
- Ogni connector ha fallback o disable-safe
- Startup riuscito anche con canali mancanti
- UI indica chiaramente coverage e confidence
- Nessun secret in chiaro nei payload esportati
- Documentazione include quickstart per setup full/partial/minimal

## KPI di successo

- Riduzione tempo diagnosi incidenti > 60%
- Rilevazione cron in ritardo entro 1 ciclo
- Identificazione lock stale/process orphan in < 30s
- Accuratezza `doing_now` > 95% su sample verificato

## Decisioni tecniche consigliate

- Backend event processing separato dal web server (no reader in-process)
- WS delta protocol con `seq` monotono e replay su reconnect
- UI con store locale normalized per evitare re-render massivi
- Introduzione test e2e su stream consistency

---

Questo blueprint è progettato per essere implementabile in step incrementali mantenendo compatibilità con l'attuale ecosistema OpenClaw.