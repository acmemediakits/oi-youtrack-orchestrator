# YouTrack Open WebUI Orchestrator

Backend OpenAPI pensato per Open WebUI che centralizza:

- ingest di richieste da testo manuale o mailbox IMAP
- classificazione e preview delle azioni
- commit controllato verso YouTrack
- audit locale di richieste, preview e commit

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
- `data/`: storage locale per richieste, preview e commit
- `.env`: token YouTrack, tenant URL, cartelle KB di default, mailbox IMAP/SMTP, filtro domini e accesso Open WebUI
- logs Docker: il worker mail scrive eventi su polling IMAP, filtro domini, chiamata Open WebUI e invio SMTP
- cartelle IMAP: `INBOX`, `PROCESSING`, `PROCESSED`, `FAILED`, `REJECTED` usate come stato operativo principale del workflow mail

## Endpoints

- `POST /requests/ingest`
- `GET /requests/{request_id}`
- `GET /projects`
- `POST /actions/preview`
- `POST /actions/commit`
- `POST /mail/poll/run`
- `GET /test?heartbeat=...`
- `GET /test?mailto=...`
- `GET /test?mailjoke=...`

## Note v1

- Il parsing linguistico usa euristiche deterministiche e non un LLM interno.
- Open WebUI può usare il backend come tool OpenAPI e lasciare al modello il compito di produrre testo/decisioni.
- La lettura IMAP è supportata via servizio dedicato e può girare in polling automatico.
- Il layer mail usa un filtro esplicito di domini mittenti autorizzati.
- Lo stato dei messaggi email è gestito principalmente via spostamento tra cartelle IMAP; il JSON locale resta solo audit tecnico.
