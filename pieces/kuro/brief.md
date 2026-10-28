# Brief — Kuro

- progetto: `/home/neuron/projects/composer/pieces/kuro/composer.project.json`
- durata 137 s · tempo 100 bpm · seed 7

## Note del compositore

Tesi: l'edificio esiste solo mentre lo ascolti. Estetica Kurokawa: rigore, monocromia, silenzi netti (tagli a zero, non dissolvenze), niente melodia. Una pulsazione nascosta a 100 bpm tiene insieme il pezzo anche quando non si sente. Il pezzo deve avere un arco: scansione, accumulo, rottura, residuo, riscansione.

## Struttura

| sezione | id | tempo | energia | densità | intenzione |
|---|---|---|---|---|---|
| Scan | `sec-scan-1` | 0–30 s | 0.15 | 0.15 | Nero, poi ping isolati su una griglia nascosta: il motivo da solo, la pulsazione si stabilisce prima di tutto il resto. Il nastro affiora appena alla fine. |
| Accretion | `sec-accretion-1` | 30–68 s | 0.55 | 0.60 | Un impatto sul battere. I pattern si addensano e sfasano, il metallo fa da controtempo, respiri di silenzio sempre più lunghi a fine frase. |
| Rupture | `sec-rupture-1` | 68–89 s | 1.00 | 1.00 | Accelerando esponenziale fino a un muro di glitch, il nastro sempre più veloce, stutter che si stringono; un ultimo impatto e poi nero lungo. |
| Residue | `sec-residue-1` | 89–119 s | 0.35 | 0.35 | Nessun impatto: un letto. Il nastro va all'indietro, il motivo torna come eco retrograda che si allontana. |
| Rescan | `sec-rescan-1` | 119–137 s | 0.10 | 0.10 | I ping dell'inizio che rallentano, il nastro che svanisce, silenzio. |

## Strumenti

### Nastro (`ins-nastro-1`)

La registrazione dell'edificio (76 s): va letta come un nastro, una testina che la attraversa lenta, veloce, all'indietro. È l'edificio stesso.

origine: file

| asset | durata | centroide | transienti/s | rms |
|---|---|---|---|---|
| `tape` | 76.069 s | 4871.9 Hz | 5.03 | -13.9 dB |

### Glitch (`ins-glitch-1`)

Glitch brevissimi (80 ms): la grammatica del pezzo. Quattro di questi possono diventare una parola che ritorna.

origine: file

| asset | durata | centroide | transienti/s | rms |
|---|---|---|---|---|
| `glitch-0` | 0.08 s | 11269.6 Hz | 0 | -13.7 dB |
| `glitch-1` | 0.08 s | 6615.8 Hz | 12.5 | -14.5 dB |
| `glitch-2` | 0.08 s | 7272.9 Hz | 12.5 | -13.5 dB |
| `glitch-3` | 0.08 s | 9828.8 Hz | 0 | -13.4 dB |
| `glitch-4` | 0.079 s | 7486.4 Hz | 0 | -19.7 dB |
| `glitch-5` | 0.057 s | 6728.1 Hz | 0 | -19.2 dB |
| `glitch-6` | 0.076 s | 6789.2 Hz | 0 | -17.3 dB |
| `glitch-7` | 0.072 s | 6533.7 Hz | 0 | -19.4 dB |
| `glitch-8` | 0.08 s | 6531.2 Hz | 0 | -13.2 dB |
| `glitch-9` | 0.08 s | 6875.6 Hz | 12.5 | -11.8 dB |
| `glitch-10` | 0.08 s | 10232.1 Hz | 0 | -13.3 dB |
| `glitch-11` | 0.08 s | 6528.5 Hz | 25 | -14 dB |
| `glitch-12` | 0.08 s | 9645.2 Hz | 0 | -16.5 dB |
| `glitch-13` | 0.07 s | 9248.2 Hz | 0 | -16.1 dB |

### Metallo (`ins-metallo-1`)

Colpi metallici: contrappunto e scansione.

origine: file

| asset | durata | centroide | transienti/s | rms |
|---|---|---|---|---|
| `metal-0` | 1.6 s | 2016.7 Hz | 3.75 | -19.4 dB |
| `metal-1` | 1.6 s | 2594.5 Hz | 11.25 | -17.4 dB |
| `metal-2` | 1.6 s | 7881.3 Hz | 0 | -19.9 dB |
| `metal-3` | 1.6 s | 2227.8 Hz | 8.12 | -19.5 dB |
| `metal-4` | 1.6 s | 4353.5 Hz | 0 | -25.2 dB |
| `metal-5` | 1.6 s | 2107.9 Hz | 0 | -21.3 dB |
| `metal-6` | 1.6 s | 984.8 Hz | 1.25 | -21 dB |
| `metal-7` | 1.6 s | 1884.6 Hz | 1.88 | -17.1 dB |
| `metal-8` | 1.6 s | 9994.7 Hz | 0 | -24.2 dB |
| `metal-9` | 1.6 s | 5361.6 Hz | 1.25 | -22.5 dB |
| `metal-10` | 1.6 s | 5169.4 Hz | 0 | -23.9 dB |
| `metal-11` | 1.6 s | 5419 Hz | 0 | -24.4 dB |

### Sub (`ins-sub-1`)

Impatti sub: i colpi che fondano le sezioni.

origine: file

| asset | durata | centroide | transienti/s | rms |
|---|---|---|---|---|
| `sub-0` | 1.8 s | 232.9 Hz | 6.11 | -9.8 dB |
| `sub-1` | 1.428 s | 205.1 Hz | 2.1 | -9.1 dB |
| `sub-2` | 0.549 s | 452.6 Hz | 1.82 | -11.5 dB |
| `sub-3` | 1.8 s | 544.8 Hz | 1.67 | -13.1 dB |
| `sub-4` | 1.428 s | 228.3 Hz | 9.1 | -10.4 dB |
| `sub-5` | 1.596 s | 329.3 Hz | 1.25 | -9 dB |
| `sub-6` | 0.479 s | 739.4 Hz | 0 | -16.9 dB |
| `sub-7` | 1.8 s | 265.1 Hz | 3.89 | -8.9 dB |

### Texture (`ins-texture-1`)

Letti lunghi, per il residuo.

origine: file

| asset | durata | centroide | transienti/s | rms |
|---|---|---|---|---|
| `texture-0` | 5.968 s | 1184 Hz | 6.87 | -9 dB |
| `texture-1` | 5.968 s | 2910.4 Hz | 1.51 | -13.1 dB |
| `texture-2` | 5.968 s | 4560.1 Hz | 1.84 | -13.8 dB |
| `texture-3` | 5.968 s | 4277.7 Hz | 8.04 | -10.3 dB |

### Schegge (`ins-schegge-1`)

Schegge digitali generate da glitchLAB, per la rottura: più taglienti dei glitch originali.

origine: glitchLAB digitale / micro · densità 0.7 · energia 0.8

| asset | durata | centroide | transienti/s | rms |
|---|---|---|---|---|
| `asset-glitch-53cdb5e948` | 0.099 s | 4044.4 Hz | 10.15 | -9.2 dB |
| `asset-glitch-24aecdf5b4` | 0.174 s | 5134.1 Hz | 11.5 | -19.2 dB |
| `asset-glitch-0e66d18ec2` | 0.311 s | 4696.5 Hz | 6.43 | -16.9 dB |
| `asset-glitch-db90866dc1` | 0.374 s | 4531.5 Hz | 5.34 | -17 dB |
| `asset-glitch-5eaa4e1df0` | 0.406 s | 5147.3 Hz | 7.4 | -16.1 dB |
| `asset-glitch-1cecf22423` | 0.518 s | 3421.6 Hz | 7.73 | -15.9 dB |

## Tavolozza

Effetti ammessi (oltre a sorgenti e mix, sempre disponibili):

- **fragment** — Stutter: a ogni burst ripete l'ultimo frammento d'ingresso (pilotato dalle regole). (slice_ms 5.0–1000.0 ms, mix 0.0–1.0 lin)
- **lowpass** —  (cutoff_hz 10.0–20000.0 Hz)

Sorgenti: **sample_player** (Legge un campione (mono o stereo); loop fino a stop.), **bank** (Fino a 16 campioni one-shot: 'play indice velocità'.), **scrub** (Testina a nastro su un campione: 'pos campione ms' (velocità = pendenza, indietro se negativa), 'amp v ms'.)

Mix: gain, clip, output

## Come comporre

Scrivi `composition.py` accanto al progetto con `def compose(c):` (vedi composer/gen.py), poi
`python -m composer compose <progetto>`: valida, archivia la versione e compila.
