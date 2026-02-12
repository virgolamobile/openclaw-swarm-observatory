# OpenClaw Portable Compliance Matrix

## Scopo

Definire cosa è protocollo OpenClaw, cosa è opzionale a runtime, e come degradare senza rompere il dashboard.

## Distinzione fondamentale

- **Protocol requirement**: canale previsto dalle regole dello sciame.
- **Runtime prerequisite**: dipendenza tecnica necessaria per avvio del tool.

Il dashboard deve rispettare i protocolli ma non deve fallire se uno o più canali non sono presenti nell'installazione.

## Matrice canali

| Canale | Protocollo OpenClaw | Runtime prerequisito | Fallback portable | Output minimo garantito |
|---|---|---|---|---|
| `shared/events/bus.jsonl` | Prescritto (broadcast) | NO | CLI/Gateway provider, oppure disable-safe | timeline eventi base |
| `shared/requests/` | Prescritto (asincrono) | NO | interaction da bus/direct messages | relazioni parziali |
| `shared/results/` | Prescritto (risultati) | NO | derive completion da milestone/eventi | completamenti stimati |
| `shared/action-ledger/*` | Prescritto (progress protocol) | NO | inferenza KPI da eventi/cron-run | KPI a confidenza media |
| `cron/jobs.json` | Prescritto da architettura | NO | `openclaw cron list --json` | next runs + health cron |
| `cron/runs/*.jsonl` | Prescritto da architettura | NO | cron state last run / summary | trend durata e status limitati |
| `agents/*/sessions/*.jsonl` | Comune ma implementation-dependent | NO | bus + cron + direct agent state | doing-now inferito |
| lock files sessione | Implementation detail | NO | watchdog/blocker events | lock insights parziali |

## Profilo raccomandato: Core-Only Passive

Questo profilo è pensato per funzionare su installazioni OpenClaw eterogenee senza dipendere da file custom locali.

### Comandi base (read-only)

| Comando | Uso |
|---|---|
| `openclaw agents list --json` | discovery agenti e workspace |
| `openclaw cron list --json` | scheduling + stato job |
| `openclaw status --json` | snapshot runtime aggregata |
| `openclaw system presence --json` | presenza gateway/nodi |
| `openclaw health` | salute infrastruttura |

### Garanzia

Se questi comandi sono disponibili, il dashboard deve:

- avviarsi sempre
- mostrare stato agenti/cron/sistema
- non richiedere modifiche ai prompt o ai file "anima" degli agenti

## Bootstrap contract

All'avvio il sistema deve produrre:

1. `capabilities.json` con stato di ogni canale
2. `coverage score` globale (0-100)
3. `mode` selezionata (`strict-openclaw`, `portable-openclaw`, `minimal`)
4. `remediation hints` per canali mancanti

## Regole di degrado

1. Nessun canale disponibile → dashboard avvia in `minimal`, mostra diagnostica setup.
2. Canali parziali → dashboard avvia in `portable`, marcando confidence per pannello.
3. Canali completi → dashboard avvia in `strict`, feature complete.

## Requisiti per pubblicazione

- Zero path hard-coded alla home utente specifica
- Supporto root custom via env/config
- Tutti i connector con `discover/snapshot/stream/health`
- Nessun crash per file/cartelle mancanti
- Test su almeno 3 profili:
  - full OpenClaw
  - partial (bus+cron senza requests/results)
  - minimal (solo CLI)

## Criterio di accettazione

Il tool è "out-of-the-box" quando, su installazione sconosciuta, mostra entro 30s:

- stato bootstrap
- capabilities rilevate
- almeno un pannello realtime popolato
- guida concreta per aumentare coverage