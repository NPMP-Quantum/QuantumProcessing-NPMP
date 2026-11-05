"""Proračun procesorskega časa v qpu.poslji brez stika z IBM (posel, storitev in Sampler so nadomestki).

Scenarij iz pregleda: obračun posla ostane "pending" (job.usage() = 0), zato skupna rezervacija ne sme pasti.
"""

import sys
from argparse import Namespace
from pathlib import Path

import pytest
from qiskit_ibm_runtime.fake_provider import FakeFez

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))
import qpu  # noqa: E402


class _Pub:
    def __init__(self, n):
        self.n = n

    def join_data(self):
        n = self.n

        class _D:
            def get_counts(self_inner):
                return {"0" * n: 500, "1" * n: 500}
        return _D()


class _Job:
    def __init__(self, vezja):
        self.vezja = vezja

    def job_id(self):
        return f"job{id(self)}"

    def result(self):
        return [_Pub(qc.num_clbits) for qc in self.vezja]

    def usage(self):
        return 0  # obračun še "pending"

    def metrics(self):
        return {"usage": {"status": "pending"}}

    def cancel(self):
        pass


@pytest.fixture
def okolje(monkeypatch, tmp_path):
    class _Seznam(list):
        pass

    omejitve = _Seznam()
    posnetki = []

    class _Sampler:
        def __init__(self, mode, options):
            omejitve.append(options["max_execution_time"])

        def run(self, pubi, shots=None):
            posnetki.append([pub[2] if isinstance(pub, tuple) and len(pub) > 2 else shots for pub in pubi])
            return _Job([pub[0] if isinstance(pub, tuple) else pub for pub in pubi])

    import qiskit_ibm_runtime
    monkeypatch.setattr(qiskit_ibm_runtime, "SamplerV2", _Sampler)
    monkeypatch.setattr(qpu, "ocena_ibm", lambda *a, **k: None)
    monkeypatch.setattr(qpu, "dejanska_poraba", lambda *a, **k: None)
    monkeypatch.setattr(qpu, "dodaj_v_dnevnik", lambda *a, **k: None)
    monkeypatch.setattr(qpu, "dopolni_zapis", lambda *a, **k: None)
    monkeypatch.setattr(qpu, "IZHOD", tmp_path)
    monkeypatch.setattr(qpu, "beri_dnevnik", lambda: [])
    omejitve.posnetki = posnetki
    return omejitve


def test_neobracunan_prejsnji_posel_ustavi_oddajo(okolje, monkeypatch):
    be = FakeFez()
    posli = [qpu.zgradi_posel(be, [("veriga", 5, False)], 8)]
    monkeypatch.setattr(qpu, "beri_dnevnik", lambda: [{"job_id": "stari", "ime_poskusa": "pilot", "fake": False,
                                                       "porabljen_cas_s": None}])
    with pytest.raises(SystemExit):
        qpu.poslji(_argumenti(100), None, be, {"usage_remaining_seconds": 598}, posli, 10)
    assert okolje == []


def test_omejitev_ni_nikoli_pod_oceno():
    with pytest.raises(SystemExit):
        qpu.omejitev_posla(Namespace(faktor_omejitve=0.1), 20.0)
    assert qpu.omejitev_posla(Namespace(faktor_omejitve=1.0), 20.0) >= 20


def _argumenti(meja, **k):
    return Namespace(max_sekund=meja, fake=False, dd="oboje", ime="t", shots=1000, shots_kal=4000, faze=8,
                     odobritev=None, max_poslov=None, faktor_omejitve=2.0, **k)


def test_vsota_omejitev_ne_preseze_meje_ko_obracun_caka(okolje):
    be = FakeFez()
    tocke = [(z, n, False) for z in ("veriga", "drevo") for n in (5, 10)]
    posli = [qpu.zgradi_posel(be, tocke, 8), qpu.zgradi_posel(be, [(z, n, True) for z, n, _ in tocke], 8)]
    ocena = qpu.ocena_casa(len(posli), sum(qpu.posnetkov_posla(v, _argumenti(45)) for _, v in posli))
    podatki = qpu.poslji(_argumenti(45), None, be, {"usage_remaining_seconds": 598}, posli, min(ocena, 45))
    assert sum(okolje) <= 45
    assert len(okolje) == 1  # drugi posel ne gre, ker prvi še drži celotno omejitev
    assert podatki["rezervirano_s"] <= 45


def test_zavrne_obstojeco_datoteko_in_prevec_poslov(okolje, tmp_path):
    be = FakeFez()
    posli = [qpu.zgradi_posel(be, [("veriga", 5, dd)], 8) for dd in (False, True)]
    (tmp_path / "t.json").write_text("{}")
    with pytest.raises(SystemExit):
        qpu.poslji(_argumenti(100), None, be, {"usage_remaining_seconds": 598}, posli, 10)
    (tmp_path / "t.json").unlink()
    a = _argumenti(100)
    a.max_poslov = 1
    with pytest.raises(SystemExit):
        qpu.poslji(a, None, be, {"usage_remaining_seconds": 598}, posli, 10)
    with pytest.raises(SystemExit):  # meja nad preostankom instance
        qpu.poslji(_argumenti(100), None, be, {"usage_remaining_seconds": 50}, posli, 10)
    assert okolje == []  # nič ni bilo poslano


def test_dd_par_v_istem_poslu_in_kalibracija_z_vec_posnetki(okolje):
    """Različici brez DD in z DD istega (zasnova, N) sta v istem poslu ena za drugo, merita iste kubite in trajata
    enako (DD doda le enokubitna vrata v čakanja). Kalibracija: 4 ponovitve vsakega vezja, vsa vezja enako posnetkov."""
    be = FakeFez()
    a = _argumenti(100)
    r = qpu.ponovitve_kalibracije(a)
    assert r == 4
    opis, vezja = qpu.zgradi_posel(be, [("veriga", 10, False), ("veriga", 10, True)], 9, r)
    brez, z_dd = opis["poskusi"]
    assert (brez["dd"], z_dd["dd"]) == (False, True)
    assert brez["zacetek"] == 2 * r and z_dd["zacetek"] == brez["zacetek"] + brez["st_vezij"]
    for i in range(brez["st_vezij"]):
        qb, qd = vezja[brez["zacetek"] + i], vezja[z_dd["zacetek"] + i]
        assert qpu.merjeni_kubiti(qb) == qpu.merjeni_kubiti(qd) == dict(enumerate(brez["postavitev"]))
        assert qb.estimate_duration(be.target) == qd.estimate_duration(be.target)
        assert qd.count_ops().get("x", 0) > qb.count_ops().get("x", 0)
    assert qpu.posnetkov_posla(vezja, a) == len(vezja) * 1000
    qpu.poslji(a, None, be, {"usage_remaining_seconds": 598}, [(opis, vezja)], 10)
    assert okolje.posnetki == [[1000] * len(vezja)]  # vsa vezja z enakim številom posnetkov
    assert "F_ubl" in brez["napoved"] and brez["kakovost"]["branje"] > 0
