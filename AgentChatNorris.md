# AgentChatNorris

## Visione MVP

AgentChatNorris e' una piattaforma agentica multi-canale progettata per supportare interazioni sincrone e asincrone con utenti, operatori e sistemi esterni.

L'MVP deve consentire di:

- offrire una chat in streaming capace di interagire con il DOM della pagina
- eseguire task agentici in modo sicuro e tracciabile
- instradare ogni richiesta verso il modello o provider piu' adatto
- gestire prompt, skill, tool e knowledge base tramite back-end e interfaccia amministrativa
- supportare multi-utente con isolamento logico, autorizzazioni e audit
- operare anche via email tramite layer IMAP/SMTP per task asincroni

Questo documento definisce il perimetro MVP da usare come input di planning e implementation.

## Obiettivi MVP

- costruire un runtime agentico unico, con canali distinti ma coerenti
- separare nettamente esperienza utente, orchestrazione, esecuzione tool e governance
- evitare dipendenza totale da un singolo vendor o frontend AI
- mantenere il sistema presentabile, estendibile e governabile fin dalla prima versione

## Canali supportati

### 1. Stream Chat

Canale interattivo principale per utente autenticato.

Capacita' MVP:

- risposta streaming stile chat assistant
- accesso controllato al DOM della pagina
- possibilita' di leggere stato UI, testo, elementi e contesto pagina
- possibilita' di proporre o eseguire azioni sul DOM solo se consentite dalla policy
- fallback a normale assistente conversazionale quando il DOM non serve

Vincoli:

- nessun accesso indiscriminato a cookie, localStorage, sessionStorage o secret presenti nel browser
- ogni azione sul DOM deve passare da un permission layer esplicito
- le operazioni mutative devono poter essere disabilitate o limitate per ruolo, pagina o sessione

### 2. Suggestion Layer

Motore che osserva contesto, ricerca o input utente e genera tag, pill o suggerimenti cliccabili.

Capacita' MVP:

- suggerimenti arricchiti a partire da query o stato pagina
- tag cliccabili che lanciano prompt predefiniti o toolchain specifiche
- suggerimenti contextualizzati per workflow, ricerca, supporto o knowledge lookup

Vincoli:

- i suggerimenti non devono eseguire direttamente azioni sensibili
- i suggerimenti devono produrre eventi tracciabili
- le suggestion devono essere componibili con la stream chat

### 3. Email Async Chat

Canale asincrono via IMAP/SMTP per task, follow-up, richieste operative e supporto.

Capacita' MVP:

- polling IMAP
- parsing email e thread reconstruction
- classificazione richiesta
- risposta via email
- integrazione con skill, KB e tool secondo policy dedicata

Vincoli:

- il canale email deve restare piu' restrittivo della chat live
- nessuna esecuzione privilegiata implicita
- difese specifiche contro prompt injection, spoofing, quote poisoning e contenuti rumorosi

## Componenti MVP

### Front-end

Responsabilita':

- UI chat streaming
- adapter DOM
- rendering suggestion/tag
- autenticazione utente e sessione
- invio eventi al runtime agentico

Funzioni chiave:

- chat panel
- action cards / clickable tags
- page context collector
- DOM bridge sicuro
- settings base utente

### Agent Runtime

Responsabilita':

- ricezione richieste dai canali
- classificazione task
- scelta della strategia
- scelta del modello
- invocazione di skill, KB e tool
- produzione risposta finale o piano operativo

Funzioni chiave:

- task classifier
- policy engine
- model router
- tool executor
- response composer
- run log / trace log

### Model Gateway / Routing

Provider target MVP:

- Open WebUI
- Ollama
- OpenAI
- Anthropic
- ElevenLabs

Responsabilita':

- astrarre i provider
- selezionare il modello per capability, latenza, costo, modalita' e rischio
- gestire credenziali e quota
- esporre un contratto unico al runtime

Decisioni MVP:

- il routing deve essere rule-based, non auto-magico
- i criteri di selezione devono essere espliciti e configurabili
- il fallback tra provider deve essere possibile ma controllato

Esempi di routing:

- DOM-aware reasoning: modello forte con tool-use affidabile
- suggestion veloci: modello piccolo ed economico
- drafting email: modello medio con buona qualita' linguistica
- voice output: ElevenLabs per sintesi

### Knowledge / Prompt / Skill Back-end

Responsabilita':

- gestione prompt di sistema
- gestione skill
- gestione knowledge base
- aggancio tool
- editor amministrativo o chat interna per definire e migliorare capabilities

Capacita' MVP:

- prompt di sistema versionati
- skill versionate come asset modificabili
- knowledge base con tagging e retrieval
- chat interna per generare o migliorare prompt, skill e integrazioni tool
- workflow di proposta e approvazione delle modifiche

Vincoli:

- il sistema non deve modificare in autonomia prompt o skill in produzione senza approvazione
- ogni modifica deve essere versionata, auditabile e revertibile

### Tool Layer

Responsabilita':

- registry centralizzato dei tool
- metadata su permessi, rischio, input e output
- esecuzione con policy per canale, ruolo e tenant

Requisiti MVP:

- tool classificati per rischio
- supporto a tool read-only e mutativi
- supporto a tool interni e provider esterni
- timeout, retry e error taxonomy

### Multi-User Layer

Responsabilita':

- autenticazione
- autorizzazione
- isolamento tra utenti, spazi o tenant
- policy per ruolo e canale

Requisiti MVP:

- utenti, ruoli e membership
- sessioni autenticate
- audit log per azioni sensibili
- policy differenziata per stream chat, suggestion e email

Ruoli minimi MVP:

- super-admin
- admin
- operator
- user
- guest

### Email Layer

Responsabilita':

- ingest IMAP
- send SMTP
- message normalization
- thread context management
- canale policy-specifico

Requisiti MVP:

- whitelist o trust policy sui domini mittenti
- parsing robusto di subject/body/thread
- rimozione rumore da footer, firme e quote
- approvazione esplicita per azioni sensibili
- registro delle elaborazioni email

## Sicurezza MVP

La sicurezza e' un requisito core, non una fase successiva.

### Principi

- zero trust per input esterni
- secret isolation
- minimo privilegio
- approvazione umana per operazioni rischiose
- auditabilita'

### Requisiti minimi

- API keys mai esposte al frontend
- provider accessibili solo dal backend/gateway
- nessun tool con accesso ai secret direttamente dal modello
- sandbox per operazioni sul DOM e per tool runtime dove possibile
- separazione delle credenziali per ambiente e provider
- logging sensibile redatto o mascherato
- rate limiting e abuse protection
- controlli anti prompt injection sul canale email e sugli input esterni
- autorizzazione per utente, canale e tipo di azione

### Segreti e credenziali

- tutti i secret devono vivere in secret storage server-side
- rotazione possibile senza deploy invasivi
- credenziali segregate per provider e per ambiente
- no hardcode di token, API keys o password in frontend o prompt

### Accesso al DOM

- consentire solo accesso mediato da bridge applicativo
- distinguere chiaramente operazioni read e write
- vietare lettura di aree marcate come sensibili
- supportare una allowlist di selettori, viste o route

## Knowledge Base MVP

Obiettivi:

- conservare documenti, policy, manuali, contesto di progetto e istruzioni operative
- rendere il contesto richiamabile dal runtime
- rendere il contenuto gestibile da interfaccia

Requisiti:

- ingest documenti
- tagging
- versioning leggero
- retrieval per topic / tag / canale
- possibilita' di attaccare KB a specifici agent profile o canali

Scelta MVP:

- retrieval esplicito e governato
- niente "magia" implicita non osservabile
- possibilita' di full-context solo su documenti piccoli o ad alta criticita'

## Skill System MVP

Le skill sono capacita' operative riusabili e versionate.

Formato concettuale:

- nome
- scopo
- quando usarla
- input attesi
- output attesi
- tool consentiti
- limiti
- esempi
- versione

Requisiti:

- skill CRUD da interfaccia o back-office
- skill richiamabili dal runtime
- skill associabili a canali o ruoli
- skill candidate generate da chat interna
- approvazione prima della pubblicazione

Apprendimento MVP:

- il sistema puo' proporre nuove skill o revisioni
- il sistema puo' spiegare perche' suggerisce la modifica
- il sistema non pubblica da solo in produzione

## Chat Interna di Progettazione

Back-end chat dedicata a:

- generare system prompt
- generare e revisionare skill
- proporre tool integration
- proporre miglioramenti a KB e policy

Questa chat non e' il runtime utente finale. E' uno spazio operativo e di governance.

Requisiti MVP:

- accesso solo utenti autorizzati
- output salvabili come draft
- comparazione tra versioni
- approvazione / publish flow

## Architettura consigliata MVP

### 1. Channel Layer

- stream chat
- suggestion engine
- email channel

### 2. Orchestration Layer

- classifier
- policy engine
- model router
- skill resolver
- KB resolver
- tool planner

### 3. Execution Layer

- provider gateway
- tool executor
- DOM bridge
- email worker

### 4. Governance Layer

- admin UI
- prompt registry
- skill registry
- knowledge registry
- audit log
- approval workflow

## Non-obiettivi MVP

- auto-modifica totalmente autonoma di skill in produzione
- multi-tenant enterprise completo con billing e org hierarchy avanzata
- marketplace plugin pubblico
- self-healing agent generalista senza supervisione
- autonomia piena su operazioni rischiose o amministrative

## Scelte di implementazione consigliate

### Open WebUI

Usarlo come:

- interfaccia utile
- gateway per alcuni provider
- componente integrabile

Non usarlo come unico cervello del sistema.

### Runtime proprietario

Costruire un runtime nostro che governa:

- canale
- policy
- routing modelli
- richiamo KB
- richiamo skill
- tool execution

### Reasoning policy

- chat stream: piu' libertà controllata
- suggestion layer: risposte rapide e deterministiche
- email: massima prudenza, massima osservabilita'

## Requisiti tecnici trasversali

- API-first design
- event logging strutturato
- tracing delle esecuzioni agentiche
- config versionata
- idempotenza dove possibile
- retry controllati
- fallback mode per provider non disponibili
- test su canali, policy e tool risk

## Deliverable MVP attesi

- chat frontend streaming con bridge DOM sicuro
- suggestion engine con tag cliccabili
- gateway multi-provider funzionante
- routing esplicito dei modelli
- admin/back-office per prompt, skill e KB
- gestione multi-utente con ruoli
- layer email IMAP/SMTP con governance dedicata
- audit trail e logging di base

## Criteri di successo MVP

- un utente autenticato puo' usare la stream chat per leggere contesto pagina e ottenere risposte utili
- il sistema puo' suggerire azioni/tag a partire dal contesto
- il runtime seleziona provider/modello coerente col task
- un admin puo' modificare prompt, skill e KB senza deploy
- un utente puo' assegnare task via email e ricevere supporto asincrono affidabile
- nessuna API key e' esposta lato client o al modello
- le azioni sensibili sono tracciate, limitate e governate

## Roadmap suggerita

### Fase 1

- model gateway
- stream chat
- policy base
- multi-user base
- prompt registry

### Fase 2

- suggestion layer
- skill registry
- KB registry
- DOM bridge hardenizzato

### Fase 3

- email async layer
- approval workflow
- skill proposal workflow
- observability piu' ricca

## Decisione architetturale guida

AgentChatNorris deve essere progettato come piattaforma agentica con runtime proprio, non come semplice customizzazione di un frontend LLM esistente.

Open WebUI puo' essere una componente importante, ma il controllo di:

- sicurezza
- policy
- routing
- skill lifecycle
- knowledge governance
- multi-user behavior

deve restare nel sistema proprietario.
