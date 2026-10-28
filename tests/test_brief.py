import struct
import wave

import pytest

from composer import compose, edit, model
from composer.gen import CompositionError
from composer.model import Asset, Project, sha256_file
from composer.validate import validate


def _wav(path, seconds=0.3, sr=48000):
    with wave.open(str(path), "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(sr)
        w.writeframes(b"".join(struct.pack("<h", 6000 if (i // 60) % 2 else -6000) for i in range(int(seconds * sr))))
    return path


@pytest.fixture
def project(tmp_path):
    p = Project(id="b", title="Brief", duration_seconds=0, tempo=100, seed=3)
    p.path = tmp_path / "composer.project.json"
    edit.add_section(p, "A", 4, "quiete", 0.2, 0.2)
    edit.add_section(p, "B", 6, "rottura", 0.9, 0.8)
    a = Asset("a1", "a1.wav", sha256_file(_wav(tmp_path / "a1.wav")))
    b = Asset("a2", "a2.wav", sha256_file(_wav(tmp_path / "a2.wav")))
    edit.add_instrument(p, "Ping", [a, b], "punti isolati")
    edit.set_palette(p, ["lowpass"])
    p.save()
    return model.load(p.path)


SCRIPT = '''
def compose(c):
    part = c.part("ping", "Ping", sections=["A", "B"], instrument="Ping")
    pl = c.player(part, "Ping", "bank", key="ping")
    c.to_bus(c.chain(pl, c.effect(part, "lowpass", key="lp", cutoff_hz=3000.0)))
    c.bus(gain=0.3)
    r = c.rng("ping")
    for t in c.grid("B"):
        if r.random() < 0.5:
            c.at(t, pl, "play", r.randrange(2), 0.8)
'''


def test_sections_are_contiguous_and_set_duration(project):
    assert [(s.start, s.end) for s in project.sections] == [(0, 4), (4, 10)]
    assert project.duration_seconds == 10
    edit.update_section(project, project.sections[0].id, duration=2)
    assert [(s.start, s.end) for s in project.sections] == [(0, 2), (2, 8)] and project.duration_seconds == 8
    edit.move_section(project, project.sections[1].id, -1)
    assert [s.name for s in project.sections] == ["B", "A"] and project.sections[1].start == 6


def test_brief_markdown_has_what_the_ai_needs(project):
    text = compose.brief_markdown(project)
    for needle in ("quiete", "rottura", "Ping", "punti isolati", "lowpass", "| `a1` | 0.3 s"):
        assert needle in text, needle


def test_compose_runs_script_versions_and_validates(project, tmp_path):
    (tmp_path / "composition.py").write_text(SCRIPT)
    version, issues = compose.run(project)
    assert version == 1 and not [i for i in issues if i.level == "error"]
    assert (tmp_path / "compositions/v001.py").read_text() == SCRIPT
    assert project.composition_meta["author"] == "claude-code"
    assert next(n for n in project.nodes if n.id == "node-master").params["gain"] == 0.3
    first = [(e.time, e.message) for e in project.events]
    version, _ = compose.run(project)
    assert version == 2 and [(e.time, e.message) for e in project.events] == first  # same seed, same piece
    assert all(4 <= e.time < 10 for e in project.events)


def test_locked_parts_survive_recomposition(project, tmp_path):
    (tmp_path / "composition.py").write_text(SCRIPT)
    compose.run(project)
    edit.update_part(project, "part-ping", locked=True)
    kept = [(e.time, e.message) for e in project.events]
    (tmp_path / "composition.py").write_text("def compose(c):\n    c.bus(gain=0.5)\n")
    compose.run(project)
    assert [(e.time, e.message) for e in project.events] == kept
    assert any(n.id == "node-lp" for n in project.nodes)
    (tmp_path / "composition.py").write_text(SCRIPT)  # touching the locked part is refused
    with pytest.raises(CompositionError):
        compose.run(project)


def test_composition_bound_to_brief(project, tmp_path):
    (tmp_path / "composition.py").write_text(SCRIPT.replace('"lowpass"', '"fragment"'))
    with pytest.raises(CompositionError, match="tavolozza"):
        compose.run(project)
    (tmp_path / "composition.py").write_text(SCRIPT.replace('instrument="Ping"', 'instrument="Violino"'))
    with pytest.raises(CompositionError, match="non nel brief"):
        compose.run(project)
    # hand edits are checked too: an effect outside the palette, an asset outside the instruments
    (tmp_path / "composition.py").write_text(SCRIPT)
    compose.run(project)
    edit.add_node(project, "fragment", "part-ping")
    project.assets.append(Asset("x", "a1.wav", ""))
    project.nodes[0].params["samples"] = ["x"]
    msgs = [i.message for i in validate(project) if i.level == "error"]
    assert any("tavolozza" in m for m in msgs) and any("nessuno strumento" in m for m in msgs)


def test_verdict_feeds_next_brief(project, tmp_path):
    (tmp_path / "composition.py").write_text(SCRIPT)
    compose.run(project)
    compose.set_status(project, "rifiutata", "troppo regolare")
    assert "troppo regolare" in compose.brief_markdown(project)
    compose.run(project)
    assert project.composition_meta["previous_feedback"] == "troppo regolare"


def test_v1_projects_migrate():
    data = {"schema_version": 1, "project": {"id": "o", "title": "o", "duration_seconds": 1},
        "nodes": [{"id": "n", "type": "lowpass"}]}
    p = model.from_dict(data)
    assert p.brief.palette == ["lowpass"] and p.composition_meta["author"] == "human"
