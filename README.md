# YouTrack Open WebUI Orchestrator

Backend OpenAPI pensato per Open WebUI che centralizza:

- ingest di richieste da testo manuale o mailbox IMAP
- classificazione e preview delle azioni
- commit controllato verso YouTrack
- query layer per ricerca progetti, issue, worklog, timing e knowledge base
- audit locale di richieste, preview e commit
- pannello web minimale per runtime config, whitelist utenti e stato bootstrap

## Avvio

1. Crea un virtualenv ed installa le dipendenze:

```bash
python3 -m venv .venv
.venv/bin/pip install -e .[dev]
```

2. Copia le variabili d'ambiente:

```bash
cp .env.example .env
```

3. Avvia il server:

```bash
.venv/bin/uvicorn app.main:app --reload
```

L'OpenAPI sarà disponibile su `/openapi.json`, direttamente riusabile come tool server in Open WebUI.

## Configurazione

- `data/client_directory.json`: rubrica clienti -> progetto YouTrack
- `data/`: storage locale per richieste, preview, commit, runtime config e whitelist utenti
- `.env`: solo secret/bootstrap come token YouTrack, tenant URL, credenziali mailbox, `PANEL_ADMIN_PASSWORD`, `SUPER_ADMIN_EMAIL`
- JSON runtime in `data/`: cartelle mailbox, domini mittenti ammessi, intervallo polling, `VERBOSE`
- logs Docker: il worker mail scrive eventi su polling IMAP, filtro domini, chiamata Open WebUI e invio SMTP
- cartelle IMAP: `INBOX`, `PROCESSING`, `PROCESSED`, `FAILED`, `REJECTED` usate come stato operativo principale del workflow mail

## Pannello Web

- login: `/panel/login`
- dashboard: `/panel`
- autenticazione: cookie HTTP-only derivato da `PANEL_ADMIN_PASSWORD`
- gestione utenti: whitelist con `full_name`, `email`, `youtrack_assignee_email`, `user_type`, `active`
- UX attuale: dashboard branded, tabella utenti, modale add/edit, sezioni runtime e secret status collapsable

## RBAC e approval

- `visitor`: puo' creare task, ricevere update e modificare solo task propri entro 30 minuti
- `team`: come visitor, ma puo' anche vedere task aperti e progetti non archiviati
- `power`: accesso avanzato via OI/API a report tempi, query avanzate, KB read/write e endpoint avanzati
- enforcement API: usa header `X-Actor-Email`
- richieste email classificate `admin_scope`: non vengono eseguite subito, ma richiedono approvazione del `SUPER_ADMIN_EMAIL` tramite token temporaneo con TTL 30 minuti

## Endpoints

- `POST /requests/ingest`
- `GET /requests/{request_id}`
- `GET /projects`
- `GET /projects/search`
- `GET /projects/{project_id}/issues`
- `GET /issues/search`
- `POST /actions/preview`
- `POST /actions/commit`
- `POST /issues/{issue_id}/work-items`
- `GET /projects/{project_id}/time-tracking/summary`
- `GET /projects/{project_id}/time-tracking/by-issue`
- `GET /projects/{project_id}/articles`
- `GET /articles/search`
- `GET /assistant/project-context`
- `GET /assistant/open-work`
- `GET /assistant/time-report`
- `POST /mail/poll/run`
- `GET /panel/login`
- `POST /panel/login`
- `POST /panel/logout`
- `GET /panel`
- `POST /panel/settings`
- `POST /panel/users`
- `GET /test?heartbeat=...`
- `GET /test?mailto=...`
- `GET /test?mailjoke=...`

## Deploy

Il compose pubblica tipicamente `8086:8000`, quindi la dashboard attesa e':

- `http://192.168.69.6:8086/panel/login`
- `http://192.168.69.6:8086/panel`

Se il panel non parte e FastAPI usa `Form(...)`, assicurarsi che l'immagine includa `python-multipart`. Dopo il fix dipendenze serve rebuild del container:

```bash
docker compose up -d --build
docker logs acme_youtrack_api --tail=100
```

## Note operative

- Il parsing mail/planner non e' piu' regex-first: il modello decide la struttura, ma il backend mantiene i guardrail.
- Open WebUI può usare il backend come tool OpenAPI e lasciare al modello il compito di produrre testo/decisioni.
- Il backend ora espone sia tool di scrittura sia tool di ricerca/listing, così l'assistente può cercare contesto prima di chiedere dettagli all'utente.
- La lettura IMAP è supportata via servizio dedicato e può girare in polling automatico.
- Il layer mail usa un filtro esplicito di domini mittenti autorizzati.
- Le email rumorose possono essere trattate in modalità helpdesk/assist senza creare ticket YouTrack di default.
- Lo stato dei messaggi email è gestito principalmente via spostamento tra cartelle IMAP; il JSON locale resta solo audit tecnico.
- Il parser Open WebUI ora alza un errore esplicito se riceve `200 OK` con payload malformato.
- In questo ambiente i test completi potrebbero non girare se mancano dipendenze Python come `pydantic`.
