"""Kuro — composition by Claude Code from brief.md (v1).

Reading of the brief: the building exists only while it is heard, so the tape (the
building) is never simply "played": a read head crosses it, and silence is a cut
to zero. One hidden grid (100 bpm sixteenths) carries everything. A four-glitch
word, chosen from the descriptors (the brightest, most different glitches), is the
thread through all five sections: alone in Scan, eroded in Accretion, drowned in
Rupture, reversed in Residue, slowing down in Rescan. The glitchLAB splinters
appear only in Rupture, taking over from the original glitches as it accelerates.
"""

from composer.analysis import describe
from composer.gen import curve, euclid

TAPE_SR = 44100


def compose(c):
    r = c.rng("kuro")
    step, bar = c.step(), c.step() * 16

    # -- orchestra ---------------------------------------------------------------------
    sec = [s.id for s in c.sections]
    tape_p = c.part("tape", "Nastro", "l'edificio", sec, "Nastro")
    tape = c.player(tape_p, "Nastro", "scrub", key="tape", amp=0.0)
    frz = c.effect(tape_p, "fragment", key="tape-freeze", slice_ms=40.0, mix=1.0)
    c.to_bus(c.chain(tape, frz))

    for key, name, ins, secs in [("glitch", "Glitch", "Glitch", sec), ("metal", "Metallo", "Metallo", sec),
                                 ("sub", "Sub", "Sub", sec), ("splinter", "Schegge", "Schegge", ["Rupture"]),
                                 ("texture", "Texture", "Texture", ["Residue", "Rescan"])]:
        part = c.part(key, name, "banco", secs, ins)
        node = c.player(part, ins, "bank", key=key)
        if key == "texture":  # the bed sinks: a lowpass that closes during Residue
            node = c.chain(node, c.effect(part, "lowpass", key="texture-lp", cutoff_hz=6000.0))
        c.to_bus(node)
    c.bus(gain=0.5)
    master = "node-master"

    # the motif: the four brightest glitches, ordered dark -> bright so the word "rises"
    gl = c.instrument("Glitch")
    cents = sorted(range(len(gl.assets)), key=lambda k: -describe(c.p.asset_path(
        next(a for a in c.p.assets if a.id == gl.assets[k])))["centroid"])
    motif = sorted(cents[:4], key=lambda k: cents.index(k), reverse=True)
    others = [k for k in range(len(gl.assets)) if k not in motif]

    tape_len = int(describe(c.p.asset_path(next(a for a in c.p.assets if a.id == "tape")))["duration"] * TAPE_SR)
    head = {"pos": 0}

    def play(t, bank, idx, vel):
        c.at(t, f"node-{bank}", "play", int(idx), round(min(vel, 1.0), 3))

    def run(t, speed, dur):
        head["pos"] = int(min(max(head["pos"] + speed * dur * TAPE_SR, 0), tape_len - 1))
        c.at(t, "node-tape", "pos", head["pos"], int(dur * 1000))

    def amp(t, v, ms):
        c.at(t, "node-tape", "amp", v, int(ms))

    def cut(t, ms):
        """A silence is a cut to zero, never a fade."""
        c.at(t, master, "hard", 0)
        c.at(t + ms / 1000, master, "hard", 1)

    def impact(t, vel):
        play(t, "sub", r.choice([1, 3, 5, 7]), vel)

    # -- Scan: black, then the word alone on the grid ----------------------------------
    a, b = c.span("Scan")
    cut(a, 1500)
    t0 = a + 1.5
    n = 0
    bars = int((b - t0) // bar)
    for k in range(bars):
        tb = t0 + k * bar
        for i, on in enumerate(euclid([1, 1, 1, 2, 1, 2, 2, 3, 2, 3, 3, 4][min(k, 11)])):
            if on and i < 12:
                play(tb + i * step, "glitch", motif[n % 4], 0.45 + 0.03 * k)
                n += 1
        if k % 4 == 0:
            play(tb, "metal", 0, 0.45 + 0.1 * (k // 4))
        if k == bars - 4:
            amp(tb, 0.12, 2500)  # the tape surfaces
        if k >= bars - 4:
            run(tb, 0.25, bar)
    cut(b - 4 * step, 4 * step * 1000)

    # -- Accretion: impact, patterns thicken and drift, breaths grow ----------------------
    a, b = c.span("Accretion")
    impact(a, 0.9)
    amp(a, 0.35, 300)
    bars = int((b - a) // bar)
    gn = 0
    for k in range(bars):
        tb, u = a + k * bar, k / max(bars - 1, 1)
        run(tb, curve(u, 0.5, 1.0), bar)
        pat, mpat = euclid(3 + round(6 * u), 16, k // 2), euclid(2 + round(3 * u), 16, k // 4 + 3)
        gap = {3: 1, 7: 2, 11: 3, 15: 8}.get(k % 16, 0)
        for i in range(16 - gap):
            ti = tb + i * step
            if pat[i]:  # the word erodes: more strangers as the section grows
                idx = motif[gn % 4] if r.random() > 0.6 * u else r.choice(others)
                play(ti, "glitch", idx, 0.6 + (0.25 if i % 4 == 0 else 0) + 0.1 * u)
                gn += 1
            if mpat[i]:
                play(ti, "metal", [2, 4, 8, 9][i % 4], 0.5 + 0.3 * u)
        if k and k % 4 == 0:
            impact(tb, 0.6 + 0.05 * (k // 4))
        if gap:
            cut(tb + (16 - gap) * step, gap * step * 1000)
    c.at(b - 1.0, "node-tape-freeze", "burst", 600, 25)
    cut(b - 0.25, 250)

    # -- Rupture: exponential accelerando, splinters take over, a wall, black -------------
    a, b = c.span("Rupture")
    impact(a, 1.0)
    amp(a, 0.5, 200)
    wall_at, black = b - 4.5 - 2.5, 4.5
    t, k, next_run, next_frz, grain = a, 0, a, a + 2.0, 40.0
    while t < wall_at:
        u = (t - a) / (wall_at - a)
        st = step * (1 / 6) ** (u ** 1.5)  # 150 ms -> 25 ms
        if t >= next_run:
            run(t, curve(u, 1.0, 3.5), 0.6)
            next_run += 0.6
        if t >= next_frz:  # freezes on the tape, tighter each time
            c.at(t, "node-tape-freeze", "burst", 300, round(grain, 1))
            grain, next_frz = max(8.0, grain * 0.7), t + 2.2 * (1 - 0.6 * u)
        if r.random() < 0.05 * u:
            cut(t, st * r.randint(1, 3) * 1000)
        elif r.random() < 0.9:
            if r.random() < u:  # glitchLAB splinters replace the original glitches
                play(t, "splinter", r.randrange(6), 0.6 + 0.4 * u)
            else:
                play(t, "glitch", r.randrange(14), 0.7 + 0.3 * u)
        if k % 4 == 0:
            play(t, "metal", r.choice([1, 3, 5, 6, 10, 11]), 0.8)
        if k % 16 == 0 and u > 0.3:
            impact(t, 0.6)
        k += 1
        t += st
    run(wall_at, 4.0, 2.5)  # the wall: 25 ms grid
    for i in range(100):
        tw = wall_at + i * 0.025
        play(tw, "splinter" if i % 3 else "glitch", r.randrange(6), 0.9)
        if i % 8 == 0:
            play(tw, "metal", r.choice([1, 3, 5]), 0.9)
    impact(wall_at + 2.5, 1.0)
    cut(wall_at + 2.85, black * 1000 - 350)

    # -- Residue: a bed, the tape backwards, the word as a receding retrograde echo -------
    a, b = c.span("Residue")
    amp(a, 0.22, 1500)
    for k in range(int((b - a) // 4)):
        run(a + 4 * k, -0.35, 4.0)
    for dt, idx, vel in [(0, 0, 0.7), (3.5, 1, 0.65), (8, 2, 0.6), (13, 3, 0.6), (19, 1, 0.55), (24, 0, 0.5)]:
        play(a + dt, "texture", idx, vel)
    for k in range(6):  # the bed sinks
        c.at(a + 5 * k, "node-texture-lp", "cutoff_hz", round(curve(k / 5, 6000, 500, "log")))
    e, gap, vel = a + 2.0, 0.3, 0.8
    for n in range(16):
        play(e, "glitch", motif[::-1][n % 4], vel)
        e, gap, vel = e + gap, gap * 1.18, vel * 0.92
    play(a + 6, "metal", 9, 0.5)
    play(a + 17, "metal", 9, 0.4)
    c.at(a + 21, "node-tape-freeze", "burst", 1500, 80)
    amp(a + 24, 0.1, 6000)

    # -- Rescan: the opening pings, slowing; the tape fades; silence ----------------------
    a, b = c.span("Rescan")
    amp(a, 0.0, 4000)
    play(a, "metal", 0, 0.35)
    e, gap = a + 0.6, 0.6
    for n in range(9):
        if e > b - 3:
            break
        play(e, "glitch", motif[n % 4], 0.7 * 0.9 ** n)
        e, gap = e + gap, gap * 1.22
    cut(b - 3.0, 2900)
