"""Osnovni poskusi: ponovitev objavljenih rezultatov v šumni simulaciji (brez procesorskega časa).

  B0  naš zagon 2. 11. 2026: 5-kubitna veriga na ibm_fez, P = 0,855 (1000 posnetkov, job dbk48fl6p51s73clupeg)
  B1  Mooney in sod. 2021: 27-kubitni GHZ na ibmq_montreal, MQC, F = 0,546 +- 0,017 z ublažitvijo branja
  B2  Wei in sod. 2020: 18-kubitni GHZ na 20-kubitnem procesorju IBM (v članku ni imenovan), MQC,
      F = 0,5165 +- 0,0036 s popravkom branja; 19 in 20 kubitov ni preseglo meje 0,5

Zagon:  .venv/bin/python src/ponovi_objave.py B0 B1 B2      (vsak del shrani rezultati/sim/ponovitev_<del>.json)
Tabela: .venv/bin/python src/ponovi_objave.py --tabela       (prebere shranjene rezultate)
"""

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import poskus  # noqa: E402

# (opis, objavljena vrednost, negotovost, katero naše število primerjamo)
OBJAVE = {
    "B0": ("ibm_fez, 5-kubitna veriga, P (surovo)", 0.855, 0.011, "surovo", "P"),
    "B1": ("Mooney 2021, ibmq_montreal, 27 kubitov, F (QREM)", 0.546, 0.017, "ublazeno", "F"),
    "B2": ("Wei 2020, 20-kubitni IBM, 18 kubitov, F (popravek branja)", 0.5165, 0.0036, "ublazeno", "F"),
}

KONFIGURACIJE = {
    "B0": [dict(backend_ime="FakeFez", zasnova_ime="veriga", n=5, metoda="pariteta", posnetki_pop=1000)],
    "B1": [dict(backend_ime="FakeMontrealV2", zasnova_ime="drevo", n=27, metoda="mqc")],
    "B2": [dict(backend_ime=b, zasnova_ime="drevo", n=18, metoda="mqc")
           for b in ("FakeJohannesburgV2", "FakePoughkeepsieV2", "FakeBoeblingenV2")],
}


def b0_razprsenost(stevilo=10, seed=5):
    """Kubitov zagona na ibm_fez nismo zapisali: P izračunamo še na naključnih 5-kubitnih verigah FakeFez."""
    import numpy as np

    import ghz
    rng = np.random.default_rng(seed)
    be = poskus.lazni_procesor("FakeFez")
    return [dict(backend_ime="FakeFez", zasnova_ime="veriga", n=5, metoda="pariteta", posnetki_pop=1000,
                 posnetki_faze_skupaj=4000, zankanje=50, postavitev=ghz.nakljucna_pot(be, 5, rng))
            for _ in range(stevilo)]


def pozeni(del_):
    zapisi = []
    konfiguracije = KONFIGURACIJE[del_] + (b0_razprsenost() if del_ == "B0" else [])
    for k in konfiguracije:
        z = poskus.izvedi(**k)
        print(del_, k["backend_ime"], poskus.vrstica(z), flush=True)
        zapisi.append(z)
        poskus.shrani(f"ponovitev_{del_}", zapisi, OBJAVE[del_][0])  # sproti, da delni rezultati ostanejo


def tabela():
    print(f"{'del':<4}{'objava':<58}{'objavljeno':>14}  {'simulacija (procesor)':<46}")
    for del_, (opis, vrednost, sigma, vrsta, kolicina) in OBJAVE.items():
        pot = poskus.IZHOD / f"ponovitev_{del_}.json"
        if not pot.exists():
            print(f"{del_:<4}{opis:<58}{vrednost:>8.4f}±{sigma:<5.4f}  (še ni pognano)")
            continue
        poskusi = json.loads(pot.read_text())["poskusi"]
        if del_ == "B0" and len(poskusi) > 1:
            vrednosti = sorted(z["surovo"]["P"] for z in poskusi[1:])
            print(f"{'':<4}{'  naključne verige FakeFez (' + str(len(vrednosti)) + ')':<58}{'':>14}  "
                  f"P od {vrednosti[0]:.3f} do {vrednosti[-1]:.3f}, mediana {vrednosti[len(vrednosti) // 2]:.3f}")
            poskusi = poskusi[:1]
        for z in poskusi:
            r = z[vrsta]
            razlika = r[kolicina] - vrednost
            print(f"{del_:<4}{opis:<58}{vrednost:>8.4f}±{sigma:<5.4f}  "
                  f"{r[kolicina]:.3f}±{r['sigma_' + kolicina]:.3f} ({z['backend']}), razlika {razlika:+.3f}; "
                  f"surovo F={z['surovo']['F']:.3f}, ublaženo F={z['ublazeno']['F']:.3f}, "
                  f"globina {z['lastnosti_po']['globina']}, 2q {z['lastnosti_po']['dvokubitna']}")


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("deli", nargs="*", choices=sorted(KONFIGURACIJE))
    ap.add_argument("--tabela", action="store_true")
    a = ap.parse_args()
    for d in a.deli:
        pozeni(d)
    if a.tabela or not a.deli:
        tabela()


if __name__ == "__main__":
    main()
