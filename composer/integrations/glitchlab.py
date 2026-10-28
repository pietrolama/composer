"""glitchLAB adapter: a catalog of sound matter, not a code dependency.

Reads glitchLAB's library/ (<id>.wav + <id>.json with DNA and descriptors)
directly, and runs its CLI for generation. Composer stores a reference, a hash
and the provenance; saved projects stay readable without glitchLAB.
"""

import json
import os
import re
import subprocess
import sys
from pathlib import Path

from ..model import Asset, sha256_file

DEFAULT_ROOT = Path(os.environ.get("GLITCHLAB_ROOT", Path.home() / "projects" / "glitchLAB"))
DESCRIPTORS = ("duration", "transients", "centroid", "noisiness", "periodicity", "silence", "rms")
ID = re.compile(r"\b([0-9a-f]{10})\b")


class GlitchLabUnavailable(RuntimeError):
    pass


class GlitchLabAdapter:
    def __init__(self, root=DEFAULT_ROOT):
        self.root = Path(root)
        self.library = self.root / "library"

    def available(self):
        return self.library.is_dir()

    def _require(self):
        if not self.available():
            raise GlitchLabUnavailable(f"libreria glitchLAB non trovata in {self.library}")

    def _meta(self, path):
        meta = json.loads(path.read_text())
        g, d = meta["dna"], meta["descriptors"]
        return {"id": meta["id"], "character": g["character"], "seed": g["seed"],
                "origin": g.get("origin"), "kept": meta.get("kept", False),
                "lineage": g.get("lineage", {}),
                "descriptors": {k: d[k] for k in DESCRIPTORS if k in d},
                "wav": str(self.library / f"{meta['id']}.wav")}

    def list_assets(self, character=None, kept=None, max_duration=None, min_duration=None):
        self._require()
        out = []
        for p in sorted(self.library.glob("*.json")):
            try:
                m = self._meta(p)
            except (json.JSONDecodeError, KeyError):
                continue
            dur = m["descriptors"].get("duration", 0)
            if character and m["character"] != character:
                continue
            if kept is not None and m["kept"] != kept:
                continue
            if max_duration is not None and dur > max_duration:
                continue
            if min_duration is not None and dur < min_duration:
                continue
            out.append(m)
        return out

    def get_asset_metadata(self, gid):
        self._require()
        path = self.library / f"{gid}.json"
        if not path.exists():
            raise KeyError(f"campione glitchLAB sconosciuto: {gid}")
        return self._meta(path)

    def import_asset(self, gid, asset_id=None, project_dir=None):
        """Build a model Asset that points at the glitchLAB file, with provenance."""
        m = self.get_asset_metadata(gid)
        wav = Path(m["wav"])
        path = os.path.relpath(wav, project_dir) if project_dir else str(wav)
        return Asset(
            id=asset_id or f"asset-glitch-{gid}",
            path=path,
            sha256=sha256_file(wav),
            provenance={"source": "glitchLAB", "glitchlab_id": gid, "character": m["character"],
                        "seed": m["seed"], "lineage": m["lineage"], "descriptors": m["descriptors"],
                        "rebuild": f"python -m glitchlab render <dna di {gid}>"})

    def generate(self, character, count=8, length="micro", density=0.5, energy=0.5, timeout=600):
        """Ask glitchLAB for new samples via its CLI; return their metadata."""
        self._require()
        proc = subprocess.run(
            [sys.executable, "-m", "glitchlab", "generate", character, "-n", str(count),
             "-l", length, "-d", str(density), "-e", str(energy)],
            cwd=self.root, capture_output=True, text=True, timeout=timeout)
        if proc.returncode != 0:
            raise GlitchLabUnavailable(proc.stderr.strip() or "glitchLAB generate fallito")
        return [self.get_asset_metadata(i) for i in ID.findall(proc.stdout)]


def generate_instrument(project, name, character, length="micro", density=0.5, energy=0.5,
                        count=8, description="", adapter=None):
    """Ask glitchLAB for a family of samples and add them to the brief as one instrument."""
    from .. import edit
    gl = adapter or GlitchLabAdapter()
    metas = gl.generate(character, count=count, length=length, density=density, energy=energy)
    if not metas:
        raise GlitchLabUnavailable("glitchLAB non ha prodotto campioni")
    assets = [gl.import_asset(m["id"], project_dir=project.path.parent) for m in metas]
    return edit.add_instrument(project, name, assets, description, {
        "type": "glitchlab", "character": character, "length": length,
        "density": density, "energy": energy, "count": count})
