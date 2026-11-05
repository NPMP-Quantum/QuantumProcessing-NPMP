"""Preverba predpostavke lokalne ublažitve branja na shranjenih kalibracijskih izidih (samo bere datoteke, nič ne odda).

Če so napake branja med kubiti neodvisne, je verjetnost izida vseh ničel (enic) enaka produktu verjetnosti po kubitih,
pričakovana parnost pa produktu (1 - 2p). Razmerje opaženo/lokalno blizu 1 pomeni, da kalibracija korelacij ne kaže.

Uporaba: python src/preveri_branje.py pilot glavni zgostitev
"""
import json
import math
import sys
from pathlib import Path

IZHOD = Path(__file__).resolve().parent.parent / "rezultati" / "qpu"


def zdruzi(seznam):
    skupno = {}
    for stetje in seznam:
        for niz, st in stetje.items():
            skupno[niz] = skupno.get(niz, 0) + st
    return skupno


def main(imena):
    print("zasnova  N  p01    p10    IBM    | P0 op/lok P1 op/lok (napaka) | par0 op/lok par1 op/lok (napaka) | faktor C")
    for ime in imena:
        podatki = json.loads((IZHOD / f"{ime}.json").read_text())
        for z in podatki["posli"]:
            if not z["stetja"]:
                continue
            k = len(z["unija"])
            r = z.get("ponovitve_kal", 1)
            kal0, kal1 = zdruzi(z["stetja"][:r]), zdruzi(z["stetja"][r:2 * r])
            vsi0, vsi1 = sum(kal0.values()), sum(kal1.values())
            for p in z["poskusi"]:
                if p.get("dd", z["dd"]) is True:  # postavitev je enaka kot pri točki brez DD
                    continue
                mesta = [k - 1 - z["unija"].index(q) for q in p["postavitev"]]
                p01 = [sum(st for niz, st in kal0.items() if niz[m] == "1") / vsi0 for m in mesta]
                p10 = [sum(st for niz, st in kal1.items() if niz[m] == "0") / vsi1 for m in mesta]
                p0 = sum(st for niz, st in kal0.items() if all(niz[m] == "0" for m in mesta)) / vsi0
                p1 = sum(st for niz, st in kal1.items() if all(niz[m] == "1" for m in mesta)) / vsi1
                par0 = sum(st * (-1) ** sum(niz[m] == "1" for m in mesta) for niz, st in kal0.items()) / vsi0
                par1 = sum(st * (-1) ** sum(niz[m] == "0" for m in mesta) for niz, st in kal1.items()) / vsi1
                lp0, lp1 = math.prod(1 - x for x in p01), math.prod(1 - x for x in p10)
                lpar0, lpar1 = math.prod(1 - 2 * x for x in p01), math.prod(1 - 2 * x for x in p10)
                nap_p0 = math.sqrt(p0 * (1 - p0) / vsi0) / lp0
                nap_p1 = math.sqrt(p1 * (1 - p1) / vsi1) / lp1
                nap_par0 = math.sqrt((1 - par0 ** 2) / vsi0) / lpar0
                nap_par1 = math.sqrt((1 - par1 ** 2) / vsi1) / lpar1
                print(f"{p['zasnova']:<7}{p['n']:>3} {sum(p01) / len(p01):.4f} {sum(p10) / len(p10):.4f} "
                      f"{p['kakovost']['branje']:.4f} | {p0 / lp0:5.3f} {p1 / lp1:5.3f} (+-{nap_p0:.3f} {nap_p1:.3f}) | "
                      f"{par0 / lpar0:5.2f} {par1 / lpar1:5.2f} (+-{nap_par0:.2f} {nap_par1:.2f}) | "
                      f"{math.prod(1 - a - b for a, b in zip(p01, p10)):.3f}")


def najslabsi_kubiti(imena, koliko=6):
    """Kubiti z največjo napako branja v katerem koli poslu, z vrednostmi po poslih: pokaže spremembe med posli."""
    tabela, tocke = {}, {}
    for ime in imena:
        podatki = json.loads((IZHOD / f"{ime}.json").read_text())
        for z in podatki["posli"]:
            if not z["stetja"]:
                continue
            k, r = len(z["unija"]), z.get("ponovitve_kal", 1)
            kal0, kal1 = zdruzi(z["stetja"][:r]), zdruzi(z["stetja"][r:2 * r])
            for mesto, q in enumerate(z["unija"]):
                m = k - 1 - mesto
                p01 = sum(st for niz, st in kal0.items() if niz[m] == "1") / sum(kal0.values())
                p10 = sum(st for niz, st in kal1.items() if niz[m] == "0") / sum(kal1.values())
                tabela.setdefault(q, {})[ime] = (p01, p10)
            for p in z["poskusi"]:
                if p.get("dd", z["dd"]) is not True:
                    for q in p["postavitev"]:
                        tocke.setdefault(q, []).append(f"{p['zasnova']} {p['n']}")
    print("\nnajslabši kubiti (p01, p10 po poslih):")
    for q in sorted(tabela, key=lambda x: -max(a + b for a, b in tabela[x].values()))[:koliko]:
        vrednosti = "; ".join(f"{i} {a:.3f} {b:.3f}" for i, (a, b) in tabela[q].items())
        print(f"q{q}: {vrednosti} | {', '.join(tocke.get(q, []))}")


if __name__ == "__main__":
    imena_poskusov = sys.argv[1:] or ["pilot", "glavni", "zgostitev"]
    main(imena_poskusov)
    najslabsi_kubiti(imena_poskusov)
