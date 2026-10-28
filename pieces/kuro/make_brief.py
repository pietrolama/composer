"""Kuro's brief: instruments and form with intentions, no score. The AI composes from here."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from composer import edit, model  # noqa: E402
from composer.model import Asset, sha256_file  # noqa: E402

HERE = Path(__file__).resolve().parent
FX = Path.home() / "projects/pureDataMCP/kuro/kuro_samples_fx"
p = model.Project(id="kuro", title="Kuro", duration_seconds=0, tempo=100, seed=7)
p.path = HERE / "composer.project.json"


def files(folder, n, prefix):
    out = []
    for k in range(n):
        f = FX / folder / f"{folder}_{k}.wav"
        out.append(Asset(f"{prefix}-{k}", str(f.relative_to(HERE, walk_up=True)), sha256_file(f),
                         {"source": "kuro_samples_fx", "file": f.name}))
    return out


tape = FX / "subassemblies_full.wav"
edit.add_instrument(p, "Nastro", [Asset("tape", str(tape.relative_to(HERE, walk_up=True)), sha256_file(tape),
                                        {"source": "registrazione"})],
                    "La registrazione dell'edificio (76 s): va letta come un nastro, una testina che la attraversa "
                    "lenta, veloce, all'indietro. È l'edificio stesso.", {"type": "file"})
edit.add_instrument(p, "Glitch", files("glitch", 14, "glitch"), "Glitch brevissimi (80 ms): la grammatica del pezzo. "
                    "Quattro di questi possono diventare una parola che ritorna.", {"type": "file"})
edit.add_instrument(p, "Metallo", files("metal", 12, "metal"), "Colpi metallici: contrappunto e scansione.",
                    {"type": "file"})
edit.add_instrument(p, "Sub", files("sub", 8, "sub"), "Impatti sub: i colpi che fondano le sezioni.",
                    {"type": "file"})
edit.add_instrument(p, "Texture", files("texture", 4, "texture"), "Letti lunghi, per il residuo.", {"type": "file"})

p.sections = []
for name, dur, energy, density, intent in [
    ("Scan", 30, 0.15, 0.15, "Nero, poi ping isolati su una griglia nascosta: il motivo da solo, la pulsazione "
                             "si stabilisce prima di tutto il resto. Il nastro affiora appena alla fine."),
    ("Accretion", 38, 0.55, 0.6, "Un impatto sul battere. I pattern si addensano e sfasano, il metallo fa da "
                                 "controtempo, respiri di silenzio sempre più lunghi a fine frase."),
    ("Rupture", 21, 1.0, 1.0, "Accelerando esponenziale fino a un muro di glitch, il nastro sempre più veloce, "
                              "stutter che si stringono; un ultimo impatto e poi nero lungo."),
    ("Residue", 30, 0.35, 0.35, "Nessun impatto: un letto. Il nastro va all'indietro, il motivo torna come eco "
                                "retrograda che si allontana."),
    ("Rescan", 18, 0.1, 0.1, "I ping dell'inizio che rallentano, il nastro che svanisce, silenzio."),
]:
    edit.add_section(p, name, dur, intent, energy, density)
p.brief.palette = ["fragment", "lowpass"]
p.brief.notes = ("Tesi: l'edificio esiste solo mentre lo ascolti. Estetica Kurokawa: rigore, monocromia, "
                 "silenzi netti (tagli a zero, non dissolvenze), niente melodia. Una pulsazione nascosta a 100 bpm "
                 "tiene insieme il pezzo anche quando non si sente. Il pezzo deve avere un arco: scansione, "
                 "accumulo, rottura, residuo, riscansione.")
p.save()
print(p.path)
