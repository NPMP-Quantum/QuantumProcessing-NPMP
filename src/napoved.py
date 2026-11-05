"""Klasična napoved zvestobe GHZ iz kalibracije procesorja (proračun napak), brez simulacije.

Za prevedeno in časovno razporejeno vezje (ALAP, čakanja kot `delay`):
  G  = prod (1 - e_g)                 verjetnost, da nobena vrata ne naredijo napake (napake iz kalibracije)
  A1 = prod exp(-tau_i / T1_i)        razpad veje |1...1> med čakanji (tau_i: čas čakanja kubita i po prvih vratih)
  D  = prod exp(-tau_i / T2_i)        izguba koherence med čakanji
  P_ubl = G (1 + A1) / 2,  C_ubl = G D                      (z idealno ublažitvijo branja)
  P_sur = G [prod(1 - p10_i) + A1 prod(1 - p01_i)] / 2,  C_sur = C_ubl prod(1 - p10_i - p01_i)
  F = (P + C) / 2
Model je grob (vsaka napaka vrat uniči stanje, čakanja so neodvisna), zato ga preverimo s šumno simulacijo pri
majhnih N. Služi za izbiro N v poskusih na procesorju in kot klasična primerjava v poročilu.

Primer: .venv/bin/python src/napoved.py --backend FakeFez --n 5 10 15 20 25 30 40 50
"""

import argparse
import math
import sys
from collections import defaultdict
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import ghz  # noqa: E402


def branje(backend, q):
    lastnosti = backend.properties() if hasattr(backend, "properties") else None
    if lastnosti is not None:
        try:
            return (lastnosti.qubit_property(q, "prob_meas1_prep0")[0], lastnosti.qubit_property(q, "prob_meas0_prep1")[0])
        except Exception:  # noqa: BLE001
            pass
    e = backend.target["measure"][(q,)].error or 0.0
    return e, e


def napoved(backend, zasnova_ime, n):
    z = ghz.zasnova_za(backend, zasnova_ime, n)
    qc = ghz.prevedi([ghz.vezje_populacija(z.priprava)], backend, z.postavitev)[0]
    t, dt = backend.target, backend.dt
    G, cakanje, zacel = 1.0, defaultdict(float), set()
    for inst in qc.data:
        ime = inst.operation.name
        qs = tuple(qc.find_bit(q).index for q in inst.qubits)
        if ime in ("barrier", "measure"):
            continue
        if ime == "delay":
            trajanje = inst.operation.duration * (dt if inst.operation.unit == "dt" else 1e-9)
            for q in qs:
                if q in zacel:
                    cakanje[q] += trajanje
            continue
        zacel.update(qs)
        lastnosti = t[ime].get(qs) if ime in t.operation_names else None
        G *= 1 - ((lastnosti.error if lastnosti is not None else 0.0) or 0.0)
    A1 = D = 1.0
    for q in z.postavitev:
        qp = t.qubit_properties[q]
        A1 *= math.exp(-cakanje[q] / qp.t1)
        D *= math.exp(-cakanje[q] / min(qp.t2, 2 * qp.t1))
    p10 = [branje(backend, q)[0] for q in z.postavitev]
    p01 = [branje(backend, q)[1] for q in z.postavitev]
    P_ubl, C_ubl = G * (1 + A1) / 2, G * D
    P_sur = G * (math.prod(1 - x for x in p10) + A1 * math.prod(1 - x for x in p01)) / 2
    C_sur = C_ubl * math.prod(1 - a - b for a, b in zip(p10, p01))
    return {"zasnova": zasnova_ime, "n": n, "G": G, "A1": A1, "D": D,
            "branje_povp": sum(p10 + p01) / (2 * n), "cakanje_povp_us": sum(cakanje[q] for q in z.postavitev) / n * 1e6,
            "F_sur": (P_sur + C_sur) / 2, "F_ubl": (P_ubl + C_ubl) / 2, "P_sur": P_sur, "C_sur": C_sur,
            "globina": ghz.lastnosti(qc)["globina"]}


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--backend", default="FakeFez")
    ap.add_argument("--zasnove", nargs="+", default=["veriga", "drevo"])
    ap.add_argument("--n", type=int, nargs="+", default=[5, 10, 15, 20, 25, 30, 40, 50])
    a = ap.parse_args()
    import qiskit_ibm_runtime.fake_provider as fp
    backend = getattr(fp, a.backend)()
    print(f"{'zasnova':<7}{'N':>4} {'globina':>8} {'G (vrata)':>10} {'D (čakanje)':>12} {'A1':>6} {'branje':>7} "
          f"{'F surovo':>9} {'F ublaž.':>9}")
    for z in a.zasnove:
        for n in a.n:
            r = napoved(backend, z, n)
            print(f"{z:<7}{n:>4} {r['globina']:>8} {r['G']:>10.3f} {r['D']:>12.3f} {r['A1']:>6.3f} {r['branje_povp']:>7.4f} "
                  f"{r['F_sur']:>9.3f} {r['F_ubl']:>9.3f}", flush=True)


if __name__ == "__main__":
    main()
