"""Preverbe vezij in analize: idealni simulator mora dati F = 1, ublažitev branja mora popraviti znano napako.

Zagon: .venv/bin/python -m pytest tests -q
"""

import math
import sys
from pathlib import Path

import numpy as np
import pytest
from qiskit_ibm_runtime.fake_provider import FakeFez

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))
import ghz  # noqa: E402

BACKEND = FakeFez()


@pytest.mark.parametrize("zasnova_ime", ["veriga", "drevo"])
@pytest.mark.parametrize("metoda", ["pariteta", "mqc"])
@pytest.mark.parametrize("n", [3, 6])
def test_idealni_simulator_da_f_1(zasnova_ime, metoda, n):
    z = ghz.zasnova_za(BACKEND, zasnova_ime, n)
    f = ghz.faze(n)
    prevedena = ghz.prevedi(ghz.vezja_poskusa(z, metoda, f), BACKEND, z.postavitev)
    stetja = ghz.pozeni(prevedena, ghz.simulator(None), shots=4000)
    r = ghz.zvestoba(stetja, n, metoda, f, ublazitev=False, zankanje=0)
    assert r["P"] == pytest.approx(1.0)
    assert r["C"] == pytest.approx(1.0, abs=0.05)


@pytest.mark.parametrize("zasnova_ime", ["veriga", "drevo"])
def test_brez_dodanih_swap(zasnova_ime):
    n = 12
    z = ghz.zasnova_za(BACKEND, zasnova_ime, n)
    pop = ghz.prevedi([ghz.vezje_populacija(z.priprava)], BACKEND, z.postavitev)[0]
    assert ghz.lastnosti(pop)["dvokubitna"] == n - 1
    assert "swap" not in pop.count_ops()


def test_drevo_plitvejse_od_verige():
    n = 20
    v = ghz.zasnova_za(BACKEND, "veriga", n)
    d = ghz.zasnova_za(BACKEND, "drevo", n)
    gv = ghz.lastnosti(ghz.prevedi([ghz.vezje_populacija(v.priprava)], BACKEND, v.postavitev)[0])["globina"]
    gd = ghz.lastnosti(ghz.prevedi([ghz.vezje_populacija(d.priprava)], BACKEND, d.postavitev)[0])["globina"]
    assert gd < gv


def test_ublazitev_branja_popravi_znano_napako():
    """Sintetični poskus: idealni GHZ (P = 1, pariteta 1 pri phi = 0) z znano napako branja na 3 kubitih."""
    rng = np.random.default_rng(1)
    n, shots = 3, 200_000
    e0, e1 = np.array([0.02, 0.03, 0.01]), np.array([0.05, 0.04, 0.06])

    def preberi(pravi_biti):
        flip = np.where(pravi_biti == 0, rng.random(pravi_biti.shape) < e0, rng.random(pravi_biti.shape) < e1)
        izmerjeni = pravi_biti ^ flip
        stetje = {}
        for vrstica in izmerjeni:
            niz = "".join(str(b) for b in reversed(vrstica))
            stetje[niz] = stetje.get(niz, 0) + 1
        return stetje

    vse0 = np.zeros((shots, n), dtype=np.int8)
    vse1 = np.ones((shots, n), dtype=np.int8)
    pol = np.repeat(rng.integers(0, 2, size=(shots, 1)), n, axis=1).astype(np.int8)
    kal0, kal1, pop = preberi(vse0), preberi(vse1), preberi(pol)

    m0, m1 = ghz.napake_branja(kal0, kal1)
    assert m0 == pytest.approx(e0, abs=0.003)
    assert m1 == pytest.approx(e1, abs=0.003)

    biti, st = ghz._v_matriko(pop)
    surovo = np.dot(ghz.utezi(biti, "vse0") + ghz.utezi(biti, "vse1"), st) / st.sum()
    popravljeno = np.dot(ghz.utezi(biti, "vse0", m0, m1) + ghz.utezi(biti, "vse1", m0, m1), st) / st.sum()
    assert surovo < 0.93
    assert popravljeno == pytest.approx(1.0, abs=0.01)


def test_koherenca_iz_sinteticnih_oscilacij():
    n = 7
    f = ghz.faze(n)
    par = [0.6 * math.cos(n * x + 0.3) + 0.05 * math.cos((n - 2) * x) for x in f]
    assert ghz.koherenca(f, par, n, "pariteta") == pytest.approx(0.6, abs=1e-9)
    s = [0.5 + 0.5 * 0.36 * math.cos(n * x) for x in f]  # MQC: I_N = 0.09 -> C = 0.6
    assert ghz.koherenca(f, s, n, "mqc") == pytest.approx(0.6, abs=1e-9)


class _IdealnoZNesimetricnimBranjem(ghz.SumniSimulator):
    """Idealen simulator, napako branja (nesimetrično) pa dodamo enako kot pri šumnem modelu."""

    def __init__(self, branje):
        from qiskit_aer import AerSimulator

        self.sim = AerSimulator(method="matrix_product_state", seed_simulator=3)
        self.branje = branje
        self.rng = np.random.default_rng(3)
        self.seed, self.klic = 3, 0


@pytest.mark.parametrize("zasnova_ime", ["veriga", "drevo"])
@pytest.mark.parametrize("metoda", ["pariteta", "mqc"])
def test_nesimetricno_branje_in_ublazitev_na_cipu(zasnova_ime, metoda):
    """Preveri pretvorbo klasični bit -> fizični kubit, smer preklopa in ublažitev na dejanski postavitvi."""
    n = 6
    z = ghz.zasnova_za(BACKEND, zasnova_ime, n)
    rng = np.random.default_rng(0)
    branje = {}
    for q in z.postavitev:
        p10, p01 = rng.uniform(0.01, 0.06), rng.uniform(0.05, 0.15)
        branje[q] = np.array([[1 - p10, p10], [p01, 1 - p01]])
    f = ghz.faze(n)
    prevedena = ghz.prevedi(ghz.vezja_poskusa(z, metoda, f), BACKEND, z.postavitev)
    sim = _IdealnoZNesimetricnimBranjem(branje)
    stetja = sim.pozeni(prevedena[:3], 20000) + sim.pozeni(prevedena[3:], 4000)
    e0, e1 = ghz.napake_branja(stetja[0], stetja[1])
    assert e0 == pytest.approx([branje[q][0][1] for q in z.postavitev], abs=0.006)
    assert e1 == pytest.approx([branje[q][1][0] for q in z.postavitev], abs=0.008)
    surovo = ghz.zvestoba(stetja, n, metoda, f, ublazitev=False, zankanje=0)
    ublazeno = ghz.zvestoba(stetja, n, metoda, f, ublazitev=True, zankanje=0)
    assert surovo["F"] < 0.9
    assert ublazeno["F"] == pytest.approx(1.0, abs=0.03)


def test_pauli_priblizek_ohrani_verjetnosti_paulijev():
    """Amplitudno dušenje na enem kubitu: Paulijev približek mora ohraniti pravilni kubit in diagonalo."""
    from qiskit_aer.noise import NoiseModel, amplitude_damping_error
    from qiskit.quantum_info import Kraus

    nm = NoiseModel()
    err = amplitude_damping_error(0.5).tensor(amplitude_damping_error(0.0))  # dušenje na višjem kubitu
    nm.add_quantum_error(err, "cz", [0, 1])
    ghz._pauli_priblizek_dvokubitnih(nm, "cz")
    nova = nm._local_quantum_errors["cz"][(0, 1)]
    # Paulijev približek dušenja z gamma = 0,5: višji kubit (oznaka levo) se preklopi z verjetnostjo
    # p_X + p_Y = gamma / 2 = 0,25 iz obeh stanj (nesimetrični del se izgubi), nižji kubit se nikoli ne preklopi.
    from qiskit.quantum_info import DensityMatrix
    for zacetno, preklopljeno in [("10", "00"), ("01", "11"), ("11", "01")]:
        verjetnosti = DensityMatrix.from_label(zacetno).evolve(Kraus(nova)).probabilities_dict()
        assert verjetnosti[preklopljeno] == pytest.approx(0.25, abs=1e-9)
        assert verjetnosti[zacetno] == pytest.approx(0.75, abs=1e-9)


def test_sumni_simulator_bere_nesimetricno_branje_iz_kalibracije():
    sim = ghz.SumniSimulator(BACKEND)
    lastnosti = BACKEND.properties()
    nesimetricni = 0
    for q in range(5):
        p10 = lastnosti.qubit_property(q, "prob_meas1_prep0")[0]
        p01 = lastnosti.qubit_property(q, "prob_meas0_prep1")[0]
        assert sim.branje[q][0][1] == pytest.approx(p10)
        assert sim.branje[q][1][0] == pytest.approx(p01)
        nesimetricni += abs(p10 - p01) > 1e-4
    assert nesimetricni > 0
    assert sim.branje_vir == "properties"


def test_zankanje_da_smiselne_negotovosti():
    """Binomska negotovost populacije in večja negotovost po ublažitvi (kalibracija se tudi vzorči)."""
    n = 3
    z = ghz.zasnova_za(BACKEND, "veriga", n)
    f = ghz.faze(n)
    prevedena = ghz.prevedi(ghz.vezja_poskusa(z, "pariteta", f), BACKEND, z.postavitev)
    sim = ghz.simulator(BACKEND)
    stetja = sim.pozeni(prevedena[:3], 2000) + sim.pozeni(prevedena[3:], 1000)
    surovo = ghz.zvestoba(stetja, n, "pariteta", f, ublazitev=False, zankanje=300)
    ublazeno = ghz.zvestoba(stetja, n, "pariteta", f, ublazitev=True, zankanje=300)
    binomska = math.sqrt(surovo["P"] * (1 - surovo["P"]) / 2000)
    assert surovo["sigma_P"] == pytest.approx(binomska, rel=0.25)
    assert ublazeno["sigma_F"] >= 0.9 * surovo["sigma_F"]


def test_polovicne_faze_izlocijo_nizje_frekvence():
    """Pariteta s šumnimi členi pri n-2, n-4 in fazo signala: M > n faz da točen C, M = 8 pri n = 20 tudi
    (ostane le člen z m = 8, tj. frekvenca n - 16)."""
    def pariteta(x, n, z_m8=0.0):
        return (0.55 * math.cos(n * x + 0.7) + 0.08 * math.cos((n - 2) * x + 0.2)
                + 0.03 * math.cos((n - 4) * x) + z_m8 * math.cos((n - 16) * x))

    for n, m in [(7, 8), (20, 21)]:
        f = ghz.faze(n, m)
        assert ghz.koherenca(f, [pariteta(x, n) for x in f], n, "pariteta") == pytest.approx(0.55, abs=1e-9)
    f = ghz.faze(20, 8)
    assert ghz.koherenca(f, [pariteta(x, 20) for x in f], 20, "pariteta") == pytest.approx(0.55, abs=1e-9)
    # edini preostali vir napake: koherenca z m = 8 hkratnimi preklopi
    assert ghz.koherenca(f, [pariteta(x, 20, 0.01) for x in f], 20, "pariteta") == pytest.approx(0.55, abs=0.011)
    with pytest.raises(ValueError):
        ghz.faze(16, 8)


@pytest.mark.parametrize("zasnova, n", [("veriga", 12), ("drevo", 25)])
def test_izkljuceni_kubiti_niso_izbrani(monkeypatch, zasnova, n):
    """Kubit iz privzete postavitve po izključitvi ni več v njej, število kubitov pa ostane enako."""
    osnovna = ghz.zasnova_za(BACKEND, zasnova, n).postavitev
    izkljuceni = {osnovna[1], osnovna[-1]}
    monkeypatch.setattr(ghz, "IZKLJUCENI_KUBITI", izkljuceni)
    nova = ghz.zasnova_za(BACKEND, zasnova, n).postavitev
    assert len(set(nova)) == n
    assert not izkljuceni & set(nova)
