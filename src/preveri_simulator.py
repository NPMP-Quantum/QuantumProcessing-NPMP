"""Preverbe šumnega simulatorja FakeFez za poročilo: relaksacija med čakanjem, model proti simulaciji, 9 faz proti polnemu naboru.

Najprej poženi src/poskus.py (ukaza sta v README), ta skripta prebere njuna izida in shrani rezultati/sim/preveri_simulator.json.
"""
import json

from qiskit import QuantumCircuit

import ghz
import napoved
from poskus import IZHOD, lazni_procesor, shrani

POSNETKI = 8000
CAKANJE_US = 20


def vezje_bell(cakanje_us):
    """Bellov par, čakanje, meritev v bazi X na obeh kubitih."""
    qc = QuantumCircuit(2, 2)
    qc.h(0)
    qc.cx(0, 1)
    if cakanje_us:
        qc.delay(cakanje_us, [0, 1], unit="us")
    qc.h([0, 1])
    qc.measure([0, 1], [0, 1])
    return qc


def pariteta(stetje):
    return sum(st * (-1) ** niz.replace(" ", "").count("1") for niz, st in stetje.items()) / sum(stetje.values())


def bell(backend):
    postavitev = ghz.najdi_pot(backend, 2)
    vezja = ghz.prevedi([vezje_bell(0), vezje_bell(CAKANJE_US)], backend, postavitev)
    brez, s_cakanjem = ghz.pozeni(vezja, ghz.simulator(backend), POSNETKI)
    return {"postavitev": postavitev, "posnetki": POSNETKI, "cakanje_us": CAKANJE_US,
            "xx_brez_cakanja": pariteta(brez), "xx_s_cakanjem": pariteta(s_cakanjem)}


def po_n(ime):
    return {p["n"]: p for p in json.loads((IZHOD / f"{ime}.json").read_text())["poskusi"]}


def main():
    backend = lazni_procesor("FakeFez")
    rez = {"bell": bell(backend), "model_proti_simulaciji": [], "faze": []}
    print(f"Bell XX: brez čakanja {rez['bell']['xx_brez_cakanja']:.3f}, po {CAKANJE_US} us {rez['bell']['xx_s_cakanjem']:.3f}")

    polni, devet = po_n("veriga_fakefez"), po_n("veriga_fakefez_9faz")
    for n in sorted(polni):
        m = napoved.napoved(backend, "veriga", n)
        p = polni[n]
        rez["model_proti_simulaciji"].append({"n": n, "model_surovo": m["F_sur"], "sim_surovo": p["surovo"]["F"],
                                              "model_ublazeno": m["F_ubl"], "sim_ublazeno": p["ublazeno"]["F"]})
        print(f"N={n}: model {m['F_sur']:.3f}/{m['F_ubl']:.3f}, simulacija {p['surovo']['F']:.3f}/{p['ublazeno']['F']:.3f} "
              f"(sigma {p['surovo']['sigma_F']:.3f}/{p['ublazeno']['sigma_F']:.3f})")
    for n in sorted(devet):
        c_polni, c_9 = polni[n]["surovo"]["C"], devet[n]["surovo"]["C"]
        s = (polni[n]["surovo"]["sigma_C"] ** 2 + devet[n]["surovo"]["sigma_C"] ** 2) ** 0.5
        rez["faze"].append({"n": n, "C_polni": c_polni, "C_9": c_9, "razlika": abs(c_polni - c_9), "sigma": s})
        print(f"N={n}: C polni nabor {c_polni:.3f}, 9 faz {c_9:.3f}, razlika {abs(c_polni - c_9):.3f} (sigma {s:.3f})")

    print(f"shranjeno: {shrani('preveri_simulator', [rez], 'preverbe šumnega simulatorja FakeFez')}")


if __name__ == "__main__":
    main()
