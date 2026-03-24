# YouTrack Open WebUI Orchestrator

Backend OpenAPI pensato per Open WebUI che centralizza:

- ingest di richieste da testo manuale o mailbox IMAP
- classificazione e preview delle azioni
- commit controllato verso YouTrack
- query layer per ricerca progetti, issue, worklog, timing e knowledge base
- audit locale di richieste, preview e commit
- pannello web minimale per runtime config, whitelist utenti e stato bootstrap

## Architettura in transizione

Il repo sta passando da monolite operativo a monorepo multi-service:

- `services/youtrack_core`: tool-core OpenAPI YouTrack
- `services/email_channel`: adapter mailbox che normalizza il canale email e delega l'orchestrazione a OpenWebUI
- panel/ops: resta temporaneamente accoppiato al tool-core per continuita' di deploy

OpenWebUI resta il solo orchestratore/model host. L'email non deve piu' comportarsi come un secondo planner indipendente.

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

Entry point separati disponibili:

```bash
.venv/bin/uvicorn services.youtrack_core.main:app --reload
.venv/bin/uvicorn services.email_channel.main:app --reload --port 8001
```

## Configurazione

- `data/client_directory.json`: rubrica clienti -> progetto YouTrack
- `data/`: storage locale per richieste, preview, commit, runtime config e whitelist utenti
- `.env`: solo secret/bootstrap come token YouTrack, tenant URL, credenziali mailbox, `PANEL_ADMIN_PASSWORD`, `SUPER_ADMIN_EMAIL`
- bootstrap architetturale:
  - `SERVICE_ROLE=monolith|tool_core|email_channel`
  - `STATE_BACKEND=json|postgres`
  - `DATABASE_URL=postgresql://...` quando si usa Postgres
- JSON runtime in `data/`: cartelle mailbox, domini mittenti ammessi, intervallo polling, `VERBOSE`
- logs Docker: il worker mail scrive eventi su polling IMAP, filtro domini, chiamata Open WebUI e invio SMTP
- cartelle IMAP: `INBOX`, `PROCESSING`, `PROCESSED`, `FAILED`, `REJECTED` usate come stato operativo principale del workflow mail

## Pannello Web

- login: `/panel/login`
- dashboard: `/panel`
- autenticazione: cookie HTTP-only derivato da `PANEL_ADMIN_PASSWORD`
- gestione utenti: whitelist con `full_name`, `email`, `youtrack_assignee_email`, `user_type`, `active`
- UX attuale: dashboard branded, tabella utenti, modale add/edit, sezioni runtime e secret status collapsable
- debug: sezione `Recent application logs` con gli eventi recenti del processo e file log in `data/app.log`

## RBAC e approval

- `visitor`: puo' creare task, ricevere update e modificare solo task propri entro 30 minuti
- `team`: come visitor, ma puo' anche vedere task aperti e progetti non archiviati
- `power`: accesso avanzato via OI/API a report tempi, query avanzate, KB read/write e endpoint avanzati
- canale Open WebUI/chat: se `OPENWEBUI_TRUSTED_CHANNEL_ENABLED=true`, gli endpoint tool possono girare senza `X-Actor-Email` e usano un actor trusted dedicato configurabile via `.env`
- enforcement API utente: se arriva `X-Actor-Email`, il backend continua a usare whitelist e RBAC reali
- canale email: resta separato dal chatbot e continua ad applicare whitelist domini mittenti, planner guardrails e approval `admin_scope`
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
- `POST /run-once` nel servizio `email_channel`

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
- Il canale Open WebUI/chat e il canale mailbox sono intenzionalmente separati: la chat gira in trusted assistant mode configurabile, mentre le email restano soggette a controlli anti-spoofing e anti-injection.
- Il planner email non e' piu' pensato come cervello hardcoded del monolite: il canale mailbox usa un orchestrator dedicato e un prompt asset esterno in `prompts/email_channel_planner.md`.
- Il backend ora espone sia tool di scrittura sia tool di ricerca/listing, così l'assistente può cercare contesto prima di chiedere dettagli all'utente.
- La lettura IMAP è supportata via servizio dedicato e può girare in polling automatico.
- Lo storage operativo ha ora un backend switchabile `json|postgres`; durante la transizione il file store resta il fallback compatibile.
- In fase di startup il backend prova anche ad assicurare le cartelle runtime IMAP (`PROCESSING`, `PROCESSED`, `FAILED`, `REJECTED`) e a sottoscriverle.
- Il layer mail usa un filtro esplicito di domini mittenti autorizzati.
- Le email rumorose possono essere trattate in modalità helpdesk/assist senza creare ticket YouTrack di default.
- Lo stato dei messaggi email è gestito principalmente via spostamento tra cartelle IMAP; il JSON locale resta solo audit tecnico.
- I messaggi già processati non vengono più lasciati in loop come `UNSEEN`: il runner li marca `Seen` e li finalizza nella cartella coerente con lo stato registrato.
- Il parser Open WebUI ora alza un errore esplicito se riceve `200 OK` con payload malformato.
- In questo ambiente i test completi potrebbero non girare se mancano dipendenze Python come `pydantic`.
- Nota client IMAP: durante il debug le cartelle runtime risultano visibili in Aurora, mentre Roundcube sulla stessa casella non le espone correttamente. Questo al momento sembra un limite del client webmail, non del backend.
