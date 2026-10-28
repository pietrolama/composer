import json
import re
import shutil
import struct
import wave
from pathlib import Path

import pytest

from composer import catalog, model
from composer.compiler import CompileError, compile_project
from composer.model import Asset, Connection, Event, Node, Part, Project, Section, sha256_file
from composer.validate import validate


def _wav(path, seconds=0.25, sr=48000):
    with wave.open(str(path), "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(sr)
        n = int(seconds * sr)
        w.writeframes(b"".join(struct.pack("<h", 8000 if (i // 50) % 2 else -8000) for i in range(n)))
    return path


@pytest.fixture
def project(tmp_path):
    wav = _wav(tmp_path / "tone.wav")
    p = Project(
        id="t", title="Test", duration_seconds=4, seed=1,
        sections=[Section("s1", "A", 0, 2), Section("s2", "B", 2, 4)],
        parts=[Part("pa", "A", source_id="a1", section_ids=["s1", "s2"]),
               Part("pb", "B", source_id="a1", section_ids=["s2"])],
        assets=[Asset("a1", "tone.wav", sha256_file(wav))],
        nodes=[Node("pa-player", "sample_player", "pa", {"gain": 0.5}),
               Node("pa-lp", "lowpass", "pa", {"cutoff_hz": 2000}),
               Node("pb-player", "sample_player", "pb", {"playback_rate": 2.0}),
               Node("master", "gain", None, {"gain": 0.8}),
               Node("out", "output", None, {})],
        connections=[Connection("c1", "pa-player.audio_out", "pa-lp.audio_in"),
                     Connection("c2", "pa-lp.audio_out", "master.audio_in"),
                     Connection("c3", "pb-player.audio_out", "master.audio_in"),
                     Connection("c4", "master.audio_out", "out.audio_in")],
        events=[Event("e1", 3, "pa-lp", "cutoff_hz 400")],
        presentation={"parts": {"pa": {"x": 10, "y": 10}}})
    p.save(tmp_path / "composer.project.json")
    return model.load(tmp_path / "composer.project.json")


def test_roundtrip(project):
    again = model.from_dict(json.loads(project.path.read_text()), project.path)
    assert again.to_dict() == project.to_dict()


def test_migrate_v0_moves_positions_to_presentation():
    data = {"project": {"id": "x", "title": "x", "duration_seconds": 1},
            "parts": [{"id": "p", "name": "p", "position": {"x": 1, "y": 2}}]}
    p = model.from_dict(data)
    assert p.presentation["parts"]["p"] == {"x": 1, "y": 2}


def test_valid_project_has_no_errors(project):
    assert not [i for i in validate(project) if i.level == "error"]


@pytest.mark.parametrize("mutate, element, fragment", [
    (lambda p: p.nodes.append(Node("x", "reverb", None)), "x", "modulo sconosciuto"),
    (lambda p: p.nodes[1].params.update(cutoff_hz=99999), "pa-lp", "fuori dai limiti"),
    (lambda p: p.connections.append(Connection("c9", "out.audio_out", "master.audio_in")), "c9", "non ha"),
    (lambda p: p.connections.append(Connection("c9", "master.audio_out", "pa-player.control")), "c9", "incompatibili"),
    (lambda p: p.parts[0].section_ids.append("nope"), "pa", "sezione inesistente"),
    (lambda p: p.events.append(Event("e9", 99, "pa", "start")), "e9", "fuori dalla durata"),
])
def test_errors_name_the_element(project, mutate, element, fragment):
    mutate(project)
    errors = [i for i in validate(project) if i.level == "error"]
    assert any(i.element == element and fragment in i.message for i in errors), errors


def _parse(pd_text):
    boxes = [l for l in pd_text.splitlines() if re.match(r"#X (obj|msg|text) ", l)]
    cables = [tuple(map(int, l[:-1].split()[2:])) for l in pd_text.splitlines() if l.startswith("#X connect")]
    return boxes, cables


def test_compile_layout_and_cables(project, tmp_path):
    out = tmp_path / "build"
    res = compile_project(project, out)
    patches = out / "patches"
    for name in ("main.pd", "part_pa.pd", "part_pb.pd", "score.txt", "composer.sample_player.pd"):
        assert (patches / name).exists()
    for f in patches.glob("*.pd"):
        boxes, cables = _parse(f.read_text())
        for s, _, d, _ in cables:
            assert s < len(boxes) and d < len(boxes), f.name
    manifest = json.loads((out / "manifest.json").read_text())
    assert manifest["id_map"]["pa-lp"]["file"] == "part_pa.pd"
    assert res["report"]["errors"] == 0
    # part A exposes one stereo outlet pair (lowpass -> master), none inward
    part_a = (patches / "part_pa.pd").read_text()
    assert part_a.count("outlet~") == 2 and "inlet~" not in part_a


def test_score_timeline(project, tmp_path):
    compile_project(project, tmp_path / "build")
    lines = (tmp_path / "build/patches/score.txt").read_text().splitlines()
    t, timed = 0.0, []
    for line in lines:
        delta, *rest = line.rstrip(";").split()
        t += float(delta)
        timed.append((t, " ".join(rest)))
    assert (0, "c-pa start") in timed
    assert (2000, "c-pb start") in timed
    assert (3000, "c-pa-lp cutoff_hz 400") in timed
    assert timed[-1] == (4000, "composer-stop bang")


def test_recompile_is_incremental(project, tmp_path):
    out = tmp_path / "build"
    compile_project(project, out)
    project.presentation["parts"]["pa"] = {"x": 500, "y": 500}  # canvas only
    assert compile_project(project, out)["changed"] == ["composer.project.json"]
    project.nodes[3].params["gain"] = 0.3  # top-level node: main.pd only
    changed = compile_project(project, out)["changed"]
    assert "patches/main.pd" in changed and "patches/part_pa.pd" not in changed


def test_errors_stop_compilation(project, tmp_path):
    project.nodes.append(Node("x", "reverb", None))
    with pytest.raises(CompileError):
        compile_project(project, tmp_path / "build")
    rep = json.loads((tmp_path / "build/reports/validation.json").read_text())
    assert rep["errors"] == 1


def test_catalog_abstractions_exist():
    for m in catalog.MODULES.values():
        assert m.pd_file().exists(), m.name


@pytest.mark.skipif(not shutil.which("pd"), reason="Pure Data non installato")
def test_pd_loads_and_renders_sound(project, tmp_path):
    np = pytest.importorskip("numpy")
    wavfile = pytest.importorskip("scipy.io.wavfile")
    from composer import pdrun
    out = tmp_path / "build"
    compile_project(project, out)
    assert pdrun.check(out)["ok"]
    res = pdrun.render(out, tmp_path / "r.wav")
    assert res["ok"], res["problems"]
    sr, x = wavfile.read(res["wav"])
    x = x.astype(float) / 2 ** 31
    rms = lambda a, b: np.sqrt(np.mean(x[int(a * sr):int(b * sr)] ** 2))
    assert rms(0.1, 1.9) > 1e-3          # part A sounding
    assert rms(2.1, 2.9) > rms(0.1, 1.9)  # part B joins
    assert rms(4.2, 4.9) < 1e-6          # stopped


def test_snapshots_do_not_alias_the_model(project):
    snap = project.to_dict()
    project.presentation["parts"]["pa"]["x"] = 999
    project.nodes[0].params["gain"] = 0.1
    assert snap["presentation"]["parts"]["pa"]["x"] == 10
    again = model.from_dict(snap)
    again.nodes[0].params["gain"] = 0.2
    again.parts[0].section_ids.append("s9")
    assert snap["nodes"][0]["params"]["gain"] == 0.5 and "s9" not in snap["parts"][0]["section_ids"]
