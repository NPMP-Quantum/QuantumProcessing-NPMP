"""En simulacijski poskus GHZ: izbira kubitov, vezja, prevajanje, zagon na simulatorju, P, C, F (surovo in z ublažitvijo).

Primeri:
  .venv/bin/python src/poskus.py --backend FakeFez --zasnova drevo --n 5 10 15 --metoda pariteta
  .venv/bin/python src/poskus.py --backend FakeMontrealV2 --zasnova drevo --n 27 --metoda mqc --ime mooney27
  .venv/bin/python src/poskus.py --backend FakeFez --zasnova veriga --n 10 --idealno
Rezultat: rezultati/sim/<ime>.json (vsi parametri, različice, lastnosti vezij, števila izidov, rezultati).
"""

from __future__ import annotations

import argparse
import json
import math
import platform
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

import qiskit
import qiskit_aer
import qiskit_ibm_runtime
import qiskit_ibm_runtime.fake_provider as fake_provider

sys.path.insert(0, str(Path(__file__).resolve().parent))
import ghz  # noqa: E402

KOREN = Path(__file__).resolve().parent.parent
IZHOD = KOREN / "rezultati" / "sim"


def lazni_procesor(ime):
    return getattr(fake_provider, ime)()


def izvedi(backend_ime, zasnova_ime, n, metoda="pariteta", dd=False, stevilo_faz=None, posnetki_pop=4000,
           posnetki_faze_skupaj=16000, posnetki_kal=4000, idealno=False, seed=11, zankanje=200, postavitev=None):
    """Vrne slovar z vsemi podatki enega poskusa (en N, ena konfiguracija).

    postavitev: izbrani kubiti verige (sicer najcenejša pot oziroma drevo na čipu)."""
    backend = lazni_procesor(backend_ime)
    if postavitev is not None:
        if zasnova_ime != "veriga" or len(postavitev) != n:
            raise ValueError("postavitev velja samo za verigo in mora imeti n kubitov")
        zasnova = ghz.ghz_veriga(postavitev)
    else:
        zasnova = ghz.zasnova_za(backend, zasnova_ime, n)
    seznam_faz = ghz.faze(n, stevilo_faz)
    posnetki_faze = max(100, math.ceil(posnetki_faze_skupaj / len(seznam_faz)))

    logicna = ghz.vezja_poskusa(zasnova, metoda, seznam_faz)
    prevedena = ghz.prevedi(logicna, backend, zasnova.postavitev, dd=dd, seed=seed)
    sim = ghz.simulator(None if idealno else backend, seed=seed)

    t0 = time.time()
    kal = ghz.pozeni(prevedena[:2], sim, posnetki_kal)
    pop = ghz.pozeni(prevedena[2:3], sim, posnetki_pop)
    faz = ghz.pozeni(prevedena[3:], sim, posnetki_faze)
    cas = time.time() - t0
    stetja = kal + pop + faz

    polne = stevilo_faz is None
    surovo = ghz.zvestoba(stetja, n, metoda, seznam_faz, ublazitev=False, polne_faze=polne, zankanje=zankanje, seed=seed)
    ublazeno = ghz.zvestoba(stetja, n, metoda, seznam_faz, ublazitev=True, polne_faze=polne, zankanje=zankanje, seed=seed)

    return {
        "backend": backend_ime, "simulator": "Aer idealni" if idealno else f"Aer + šumni model {backend_ime}",
        "zasnova": zasnova_ime, "n": n, "metoda": metoda, "dd": dd,
        "faze": "2N+2 (DFT)" if polne else f"{stevilo_faz} (pol kroga, DFT)", "stevilo_faz": len(seznam_faz),
        "posnetki": {"kalibracija": posnetki_kal, "populacija": posnetki_pop, "na_fazo": posnetki_faze},
        "seed": seed, "postavitev": zasnova.postavitev,
        "lastnosti_pred": ghz.lastnosti(logicna[2]),
        "lastnosti_po": ghz.lastnosti(prevedena[2], backend.target),
        "lastnosti_po_fazno": ghz.lastnosti(prevedena[3], backend.target),
        "napaka_branja_vir": getattr(sim, "branje_vir", None),
        "surovo": surovo, "ublazeno": ublazeno, "cas_simulacije_s": round(cas, 1),
        "stetja_populacija": pop[0],
    }


def razlicice():
    return {"python": platform.python_version(), "qiskit": qiskit.__version__, "qiskit_aer": qiskit_aer.__version__,
            "qiskit_ibm_runtime": qiskit_ibm_runtime.__version__}


def shrani(ime, zapisi, opis=""):
    IZHOD.mkdir(parents=True, exist_ok=True)
    pot = IZHOD / f"{ime}.json"
    pot.write_text(json.dumps({"cas": datetime.now(timezone.utc).isoformat(timespec="seconds"), "opis": opis,
                               "razlicice": razlicice(), "poskusi": zapisi}, indent=1, ensure_ascii=False))
    return pot


def vrstica(z):
    s, u = z["surovo"], z["ublazeno"]
    return (f"N={z['n']:>3} {z['zasnova']:<6} {z['metoda']:<8} dd={int(z['dd'])} "
            f"globina {z['lastnosti_po']['globina']:>4} 2q {z['lastnosti_po']['dvokubitna']:>3} "
            f"(fazno vezje: {z['lastnosti_po_fazno']['globina']}, {z['lastnosti_po_fazno']['dvokubitna']}) | "
            f"surovo F={s['F']:.3f}±{s['sigma_F']:.3f} (P={s['P']:.3f}, C={s['C']:.3f}) | "
            f"ublaženo F={u['F']:.3f}±{u['sigma_F']:.3f} | {z['cas_simulacije_s']} s")


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--backend", default="FakeFez")
    ap.add_argument("--zasnova", choices=["veriga", "drevo"], default="drevo")
    ap.add_argument("--n", type=int, nargs="+", required=True)
    ap.add_argument("--metoda", choices=["pariteta", "mqc"], default="pariteta")
    ap.add_argument("--dd", action="store_true", help="dinamično razklapljanje (X-X) v čakanjih")
    ap.add_argument("--stevilo-faz", type=int, default=None, help="namesto 2N+2 faz uporabi toliko faz in prilagajanje")
    ap.add_argument("--posnetki-faze-skupaj", type=int, default=16000)
    ap.add_argument("--posnetki-pop", type=int, default=4000)
    ap.add_argument("--idealno", action="store_true", help="idealni simulator (brez šuma) na istih prevedenih vezjih")
    ap.add_argument("--seed", type=int, default=11)
    ap.add_argument("--ime", default=None, help="ime izhodne datoteke v rezultati/sim/")
    a = ap.parse_args()

    zapisi = []
    for n in a.n:
        z = izvedi(a.backend, a.zasnova, n, a.metoda, a.dd, a.stevilo_faz, a.posnetki_pop, a.posnetki_faze_skupaj,
                   idealno=a.idealno, seed=a.seed)
        print(vrstica(z), flush=True)
        zapisi.append(z)
    ime = a.ime or f"{a.backend}_{a.zasnova}_{a.metoda}{'_dd' if a.dd else ''}{'_ideal' if a.idealno else ''}"
    print("shranjeno:", shrani(ime, zapisi).relative_to(KOREN))


if __name__ == "__main__":
    main()
