import shutil
import struct
import subprocess
import wave
from pathlib import Path

import pytest

from composer import edit, model, rules
from composer.compiler import compile_project
from composer.model import Asset, Node, Part, Project, Rule, Section, sha256_file
from composer.validate import validate

PD_MODULES = Path(__file__).parent.parent / "composer" / "pd_modules"


def _clicks(path, hits=(0.1, 0.3, 0.6), length=0.8, sr=48000):
    """Silence with short noise bursts at known times."""
    import random
    rnd = random.Random(1)
    n = int(length * sr)
    data = [0] * n
    for h in hits:
        for i in range(int(h * sr), int(h * sr) + 240):
            data[i] = int(20000 * (rnd.random() * 2 - 1))
    with wave.open(str(path), "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(sr)
        w.writeframes(b"".join(struct.pack("<h", v) for v in data))
    return path


@pytest.fixture
def project(tmp_path):
    wav = _clicks(tmp_path / "clicks.wav")
    p = Project(
        id="r", title="Rules", duration_seconds=10, seed=7,
        sections=[Section("s1", "A", 0, 4), Section("s2", "B", 4, 10)],
        parts=[Part("src", "Impulsi", source_id="a", section_ids=["s2"]),
               Part("tex", "Texture", source_id="a", section_ids=["s1", "s2"])],
        assets=[Asset("a", "clicks.wav", sha256_file(wav))],
        nodes=[Node("src-player", "sample_player", "src", {"playback_rate": 1.0}),
               Node("tex-player", "sample_player", "tex"),
               Node("tex-frag", "fragment", "tex"),
               Node("out", "output", None)],
        rules=[Rule("r1", "src", "tex", "on_onset", "fragment",
                    {"probability": 1.0, "window_ms": 100.0, "min_gap_ms": 0.0})])
    edit.connect(p, "tex-player.audio_out", "tex-frag.audio_in")
    edit.connect(p, "tex-frag.audio_out", "out.audio_in")
    edit.connect(p, "src-player.audio_out", "out.audio_in")
    p.save(tmp_path / "composer.project.json")
    return model.load(tmp_path / "composer.project.json")


def test_onsets_found_at_known_times(project):
    hits, length = rules.onsets(project.asset_path(project.assets[0]))
    assert length == pytest.approx(0.8)
    assert [round(h, 2) for h in hits] == [0.1, 0.3, 0.6]


def test_onset_triggers_follow_loops_and_sections(project):
    exp = rules.expand(project, project.rules[0])
    times = [t for t, _, _ in exp.events]
    # source active 4-10 s, looping every 0.8 s: hits at 4.1, 4.3, 4.6, 4.9, ...
    assert times[:4] == pytest.approx([4.1, 4.3, 4.6, 4.9])
    assert all(4 <= t < 10 for t in times)
    assert exp.triggers == len(times)  # probability 1, no gap


def test_playback_rate_scales_onsets(project):
    project.nodes[0].params["playback_rate"] = 2.0
    times = [t for t, _, _ in rules.expand(project, project.rules[0]).events]
    assert times[:4] == pytest.approx([4.05, 4.15, 4.3, 4.45])


def test_same_seed_same_events_other_seed_differs(project):
    project.rules[0].params.update(probability=0.5)
    a = rules.expand(project, project.rules[0]).events
    assert rules.expand(project, project.rules[0]).events == a
    project.seed = 8
    assert rules.expand(project, project.rules[0]).events != a


def test_rules_have_independent_streams(project):
    project.rules[0].params.update(probability=0.5)
    before = rules.expand(project, project.rules[0]).events
    project.rules.append(Rule("r2", "s1", "tex", "random", "fragment", {"rate_hz": 3.0}))
    assert rules.expand(project, project.rules[0]).events == before


def test_min_gap_and_window_clipping(project):
    project.rules[0].params.update(min_gap_ms=250.0, window_ms=5000.0)
    events = rules.expand(project, project.rules[0]).events
    times = [t for t, _, _ in events]
    assert all(b - a >= 0.25 for a, b in zip(times, times[1:]))
    assert all(t + m[1] / 1000 <= 10 + 1e-6 for t, _, m in events)  # never past the part's end


def test_clock_triggers_stay_in_source_span(project):
    rule = Rule("r3", "s1", "tex", "every", "fragment", {"period_ms": 500.0, "probability": 1.0, "window_ms": 50.0})
    times = [t for t, _, _ in rules.expand(project, rule).events]
    assert times == pytest.approx([0.5 * k for k in range(8)])  # phase 0: first pulse at the span start


@pytest.mark.parametrize("change, fragment", [
    (lambda r: setattr(r, "when", "on_beat"), "'when' sconosciuto"),
    (lambda r: setattr(r, "effect", "reverse"), "'effect' sconosciuto"),
    (lambda r: r.params.update(probability=2.0), "fuori dai limiti"),
    (lambda r: r.params.update(colour=1.0), "parametro sconosciuto"),
    (lambda r: setattr(r, "target", "src"), "non contiene un modulo"),
    (lambda r: r.params.update(slice_ms_min=200.0, slice_ms_max=50.0), "slice_ms_min"),
])
def test_rule_validation(project, change, fragment):
    change(project.rules[0])
    msgs = [i.message for i in validate(project) if i.element == "r1" and i.level == "error"]
    assert any(fragment in m for m in msgs), msgs


def test_compiled_score_contains_rule_events(project, tmp_path):
    compile_project(project, tmp_path / "build")
    score = (tmp_path / "build/patches/score.txt").read_text()
    assert score.count("c-tex-frag burst") == len(rules.expand(project, project.rules[0]).events)
    import json
    rep = json.loads((tmp_path / "build/reports/rules.json").read_text())
    assert rep["seed"] == 7 and rep["rules"]["r1"]["events"][0]["time"] == pytest.approx(4.1)


@pytest.mark.skipif(not shutil.which("pd"), reason="Pure Data non installato")
def test_fragment_module_repeats_last_slice(tmp_path):
    np = pytest.importorskip("numpy")
    wavfile = pytest.importorskip("scipy.io.wavfile")
    shutil.copy(PD_MODULES / "composer.fragment.pd", tmp_path)
    (tmp_path / "t.pd").write_text(r"""#N canvas 0 0 600 400 10;
#X obj 20 20 loadbang;
#X msg 120 20 \; pd dsp 1;
#X obj 20 50 phasor~ 0.5;
#X obj 20 90 composer.fragment 60 1;
#X obj 20 130 tabwrite~ out;
#X obj 200 130 table out 48000;
#X obj 20 160 del 100;
#X msg 20 190 burst 400 50;
#X obj 300 20 del 1100;
#X msg 300 50 write -wave -bytes 4 -rate 48000 out.wav out;
#X obj 300 80 soundfiler;
#X msg 300 110 \; pd quit;
#X connect 0 0 1 0;
#X connect 2 0 3 1;
#X connect 2 0 3 2;
#X connect 3 0 4 0;
#X connect 0 0 4 0;
#X connect 0 0 6 0;
#X connect 6 0 7 0;
#X connect 7 0 3 0;
#X connect 0 0 8 0;
#X connect 8 0 9 0;
#X connect 9 0 10 0;
#X connect 10 0 11 0;
""")
    subprocess.run(["pd", "-batch", "-nogui", "-nosound", "-noprefs", "-r", "48000", "t.pd"],
                   cwd=tmp_path, timeout=30, check=True, capture_output=True)
    sr, x = wavfile.read(tmp_path / "out.wav")
    x = x.astype(float)
    ramp_rate = 0.5 / sr  # phasor~ 0.5 Hz
    burst = x[int(0.12 * sr):int(0.48 * sr)]
    assert burst.max() < 0.051 and burst.min() > 0.024  # only values from the 50 ms before the burst
    period = np.argmax([np.dot(burst[:-k], burst[k:]) / (len(burst) - k) for k in range(1200, 3600)]) + 1200
    assert period / sr * 1000 == pytest.approx(50, abs=1)
    after = x[int(0.6 * sr):int(0.7 * sr)]
    assert np.allclose(np.diff(after), ramp_rate, atol=1e-6)  # dry again
