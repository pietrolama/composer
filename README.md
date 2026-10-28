# Composer

Ambiente per la composizione assistita: **tu scrivi il brief, l'IA compone,
il compilatore genera la patch Pure Data**.

| chi | cosa |
|---|---|
| tu, nella scheda **Brief** | strumenti (generati con glitchLAB, dalla sua libreria o da file), tavolozza di effetti (astrazioni del catalogo), struttura in sezioni con intenzione (durata, energia, densità, parole), note |
| l'IA (Claude Code, dalla chat) | legge `brief.md`, scrive `composition.py` (`compose(c)` con `composer/gen.py`), esegue `composer compose`: parti, catene, eventi |
| il compilatore | composizione → cartella Pd autosufficiente, verificata e renderizzabile |
| tu, nella scheda **Composizione** | ascolti, **Accetta** / **Rifiuta…** con un commento (lo legge la versione successiva), blocchi parti, **Ricomponi** con un altro seed |

Flusso: *Nuovo* → brief → *Prepara brief per Claude* → in chat «componi» →
la nuova versione compare da sola → *▶ Ascolta* → verdetto. Ogni versione è
archiviata in `compositions/vNNN.py|json`; le parti bloccate sopravvivono alle
ricomposizioni; la composizione può usare solo gli strumenti e gli effetti del
brief (verificato in validazione).

Esempio: `pieces/kuro/` — il brief di Kuro (strumenti + 5 sezioni con le loro
intenzioni + uno strumento glitchLAB nuovo) e la composizione che ne ho tratto.
`examples/kuro/` è invece la traduzione letterale della vecchia partitura (1016
eventi), utile solo come confronto.

Stato: **milestone 01–03** (modello dati, compilatore, canvas + inspector) e
**regole compositive** compilate in eventi deterministici dal seed. Timeline
visuale con clip e automazioni (resto della 04), controllo via MCP (05) e IA (06)
sono i passi successivi.

## Regole compositive

Una `composition_rule` non è un cavo: è una relazione ("quando la sorgente fa X,
il bersaglio fa Y") che il compilatore trasforma in eventi della partitura,
calcolati dal seed del progetto. Stesso progetto + stesso seed = stessa partitura
e render identico bit per bit; ogni regola ha il suo flusso casuale
(`seed:rule_id`), quindi modificarne una non rimescola le altre.

| `when` | trigger | parametri |
|---|---|---|
| `on_onset` | attacchi nei campioni della parte sorgente, seguendo loop e `playback_rate` | `sensitivity` (salita di 12−9·s dB in 5 ms) |
| `every` | un impulso ogni `period_ms` (± `jitter`) mentre la sorgente (parte o sezione) è attiva | `period_ms`, `jitter` |
| `random` | trigger di Poisson | `rate_hz` |

| `effect` | cosa fa | parametri |
|---|---|---|
| `fragment` | burst sui moduli `fragment` del bersaglio: ripete l'ultimo frammento di `slice_ms_min..max` per `window_ms` | `window_ms`, `probability`, `slice_ms_min`, `slice_ms_max`, `min_gap_ms` |

Gli eventi generati sono in `reports/rules.json` e contati in `manifest.json`.
Nella GUI le regole sono frecce tratteggiate tra le parti (clic destro su una
parte → "Nuova regola verso"); l'inspector mostra trigger → eventi e, senza
selezione, il seed con il pulsante "nuovo" per ascoltare un'altra variante.

## Interfaccia

```
python3 -m venv .venv --system-site-packages && .venv/bin/pip install PySide6
./composer-ui examples/fracture-study/composer.project.json
```

- **Canvas**: clic destro → aggiungi modulo (dentro una cornice = in quella parte);
  trascina da un'uscita a un ingresso per collegare; `Canc` elimina; `Ctrl+D` duplica
  i nodi selezionati con i cavi tra loro; rotella = zoom, tasto centrale = pan, `F` adatta.
- **Inspector**: parametri del nodo con unità e limiti del catalogo; per una parte
  nome, ruolo, campione, sezioni, blocco.
- **Browser**: moduli, parti, campioni del progetto, libreria glitchLAB
  (doppio clic = importa con hash e provenienza).
- **Problemi**: validazione dal vivo; clic su un problema seleziona l'elemento.
- **Genera patch / Verifica in Pd / Render / ▶ Ascolta** (`pw-jack pd -jack`).
- Ogni modifica passa da `composer/edit.py` ed è un passo di annulla/ripeti
  (snapshot dell'intero modello). Gli errori di modifica (cicli, tipi di porta,
  limiti) vengono rifiutati senza toccare il modello.

```
python3 -m composer validate examples/fracture-study/composer.project.json
python3 -m composer compile  examples/fracture-study/composer.project.json -o build/fracture-study
python3 -m composer check    build/fracture-study          # carica main.pd in Pd headless
python3 -m composer render   build/fracture-study          # render offline → build/.../render.wav
pw-jack pd -jack build/fracture-study/patches/main.pd      # ascolto (parte da solo)

python3 -m composer assets --character violento --max-duration 2   # catalogo glitchLAB
python3 -m composer import <progetto.json> <glitchlab_id> --as asset-x
.venv/bin/python -m pytest tests                 # include i test GUI offscreen
```

Requisiti: Python 3.10+, Pure Data vanilla 0.55. Nessuna dipendenza Python per
il core; `numpy`/`scipy` solo per i test audio.

## Moduli

| Modulo | Ruolo |
|---|---|
| `model.py` | modello canonico a tre livelli (composizione, grafo sonoro, presentazione), ID persistenti, schema versionato + migrazioni |
| `catalog.py` | moduli ammessi: porte tipizzate (audio stereo / controllo), parametri con unità e limiti |
| `pd_modules/` | astrazioni Pd scritte a mano e testate, una per modulo del catalogo |
| `validate.py` | validazione semantica: ogni problema nomina l'elemento che lo causa |
| `pdgraph.py` | grafo Pd intermedio per chiave (indici assegnati solo in serializzazione) |
| `compiler.py` | progetto → cartella autosufficiente; riscrive solo i file cambiati |
| `edit.py` | modifiche al modello condivise da GUI, CLI e (in futuro) proposte IA |
| `ui/` | PySide6: canvas (`QGraphicsScene`), inspector, finestra con undo/redo |
| `rules.py` | regole → eventi: attacchi dei campioni, clock, Poisson; un flusso casuale per regola |
| `gen.py` | strumenti di composizione per l'IA: parti, player, effetti, bus, eventi, griglia, euclidei, curve, rng per nome |
| `compose.py` | brief.md, esecuzione di composition.py con versioni e parti bloccate, verdetti |
| `analysis.py` | descrittori di qualsiasi WAV (durata, centroide, transienti/s, rms) per il brief |
| `pdrun.py` | verifica di caricamento e render offline con Pd reale (`-batch`) |
| `integrations/glitchlab.py` | catalogo glitchLAB letto da `library/`, import con hash e provenienza, generazione via CLI |

## Cartella generata

```
build/<id>/
├── composer.project.json   snapshot con percorsi asset locali
├── assets/                 campioni usati
├── patches/
│   ├── main.pd             trasporto, parti, nodi di primo livello, bus
│   ├── part_<id>.pd        un'astrazione per parte (porte di confine calcolate)
│   ├── score.txt           timeline per [qlist]: sezioni + eventi
│   └── composer.*.pd       moduli del catalogo usati
├── manifest.json           versioni, moduli, mappa id → oggetti Pd, hash
└── reports/validation.json
```

## Convenzioni runtime

- Ogni parte e ogni nodo ricevono messaggi su `c-<id>` (es. `c-node-filter cutoff_hz 600`).
- `composer-play` / `composer-stop` avviano e fermano la timeline; `main.pd` parte al loadbang.
- Tutte le uscite si sommano in `catch~ composer-L/R` → `dac~` e `s~ composer-bus-L/R`.
- Moduli: inlet 0 = controllo; una porta audio è una coppia stereo di inlet~/outlet~.
- `composition_rule` è salvata e validata ma non ancora compilata.
- Il canvas (`presentation`) non viene mai letto dal compilatore.

## Integrazioni

- **glitchLAB** (`~/projects/glitchLAB`, o `GLITCHLAB_ROOT`): letto come catalogo,
  nessun import del suo codice. I WAV sono mono 48 kHz; il player li legge alla
  loro frequenza di campionamento qualunque sia quella di Pd.
- **Pd-MCP-Server** (`pureDataMCP/Pd-MCP-Server`): OSC unidirezionale verso UDP
  5000 (`/pd/dsp`, `/pd/set/...`, create/connect nel subpatch workspace); `get_param`
  non restituisce valori e load/save non sono implementati lato Pd. Composer non ne
  dipende per compilare; l'adattatore di controllo è la milestone 05.

## Trappole Pd incontrate

- `$0` in un message box attivato al loadbang si espande a `0`: costruire i
  messaggi con `[list append $0-x]`.
- `$N` dentro `[expr]` non riceve l'argomento dell'astrazione: passarlo da un inlet.
- `[msg set 0 \, $1 $2(` si spezza alla virgola: salvare la lista in `[list]`.
- `writesf~` si blocca in `-batch`: il render usa `tabwrite~` + `soundfiler write`.
- `[del 0]` in un loop di retrigger congela Pd: durata minima 1 ms.
- `[qlist]` non ha `stop`: si ferma con `rewind`.
