"""Poskus GHZ na pravem procesorju IBM (privzeto ibm_fez) s strogim nadzorom porabe procesorskega časa.

Ukazi (nič se ne pošlje brez `poslji`; `poslji` brez --max-sekund se ne izvede):
  nacrt     zgradi in prevede vezja, izpiše tabelo, oceno časa in preostanek na instanci
  poslji    isto + oddaja (en posel na ukaz; DD je v vezjih, zato sta DD da/ne istega N v istem poslu). Posel dobi
            max_execution_time (faktor x ocena + 3 s), ki ga pred oddajo rezervira v meji --max-sekund tega ukaza;
            rezervacija se sprosti šele po obračunu. Ukaz zavrne oddajo, dokler kateri od prejšnjih poslov ni obračunan,
            zato naj bo --max-sekund dogovorjena meja minus že porabljeni čas.
  prevzemi  izide že oddanih poslov (če je bilo čakanje prekinjeno)
  analiza   P, C, F (surovo in z ublažitvijo branja) za vse poskuse iz rezultati/qpu/<ime>.json

Zasnova: za vsak (zasnova, N, DD) 1 populacijsko vezje + M paritetnih (M faz na pol kroga, privzeto 9; N ne sme biti
večkratnik M), v vsakem poslu še kalibracijski vezji |0...0> in |1...1> na vseh uporabljenih kubitih, vsako ponovljeno
round(shots_kal / shots)-krat, ker imajo vsa vezja v poslu enako število posnetkov.

Žeton in instanca: QISKIT_IBM_TOKEN in QISKIT_IBM_INSTANCE iz okolja ali iz .env (predloga .env.example), npr.
  .venv/bin/python src/qpu.py nacrt --ime pilot --n-veriga 10 22 --n-drevo 20 40 --dd oboje
Lokalni preizkus celotne poti brez procesorja: --fake (FakeFez in šumni simulator).
"""

from __future__ import annotations

import argparse
import json
import math
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

from qiskit.transpiler import generate_preset_pass_manager

sys.path.insert(0, str(Path(__file__).resolve().parent))
import ghz  # noqa: E402
from ibm_skupno import (KOREN, beri_dnevnik, dodaj_v_dnevnik, dopolni_zapis, povezi, st_dvokubitnih,  # noqa: E402
                        stetja_iz_rezultata)

CAS_POSEL_S = 2.0          # model porabe (poročilo, enačba g20:eq:cas); pilotni posel ga preveri
CAS_POSNETEK_S = 0.35e-3
OZNAKA = "skupina20"
IZHOD = KOREN / "rezultati" / "qpu"


def ocena_casa(st_poslov, posnetkov):
    """Model porabe: fiksni del na posel + čas na posnetek (posnetkov = vsota posnetkov vseh vezij)."""
    return CAS_POSEL_S * st_poslov + CAS_POSNETEK_S * posnetkov


def povezava(ime, fake):
    """(service, backend, poraba). Pri --fake brez omrežja in brez žetona."""
    if fake:
        from qiskit_ibm_runtime.fake_provider import FakeFez
        return None, FakeFez(), {}
    service = povezi()
    try:
        poraba = service.usage()
    except Exception as e:  # noqa: BLE001
        sys.exit(f"Porabe instance ni bilo mogoče prebrati ({e}); brez nje ne nadaljujem.")
    return service, service.backend(ime), poraba


def prevedi_za_procesor(vezja, backend, postavitev, seed=7):
    pm = generate_preset_pass_manager(optimization_level=1, backend=backend, initial_layout=postavitev,
                                      seed_transpiler=seed)
    return pm.run(vezja)


def kakovost_kubitov(backend, postavitev):
    """Povprečna napaka branja, dvokubitnih vrat (po povezavah verige ali drevesa) in T2 izbranih kubitov."""
    branje, vrata, sosedi, _ = ghz.napake(backend)
    povezave = [tuple(sorted((a, b))) for a in postavitev for b in sosedi[a] if b in postavitev and a < b]
    t2 = [backend.target.qubit_properties[q].t2 for q in postavitev]
    return {"branje": sum(branje[q] for q in postavitev) / len(postavitev),
            "dvokubitna": sum(vrata[e] for e in povezave) / max(1, len(povezave)),
            "t2_us": 1e6 * sum(t2) / len(t2)}


def merjeni_kubiti(qc):
    """Slovar klasični bit -> fizični kubit za meritve v prevedenem vezju."""
    return {qc.find_bit(i.clbits[0]).index: qc.find_bit(i.qubits[0]).index for i in qc.data if i.operation.name == "measure"}


def zgradi_posel(backend, tocke, stevilo_faz, ponovitve_kal=1):
    """Vezja enega posla za točke (zasnova, N, dd): [kal_0 x r, kal_1 x r, nato za vsako točko populacija + M faz].

    Vsa vezja imajo enako število posnetkov (različno število v enem poslu je v qiskit-ibm-runtime opuščeno), zato
    kalibracijo z več posnetki dosežemo s ponovitvami: r = ponovitve_kal kopij vsakega kalibracijskega vezja.

    DD je v samem vezju (razpored ALAP, zaporedje X-X v čakanjih), zato sta različici brez DD in z DD istega
    (zasnova, N) v istem poslu ena za drugo: primerjava DD ni odvisna od spremembe kalibracije med posli.
    Obe različici imata enak časovni razpored (eksplicitna čakanja), razlikujeta se samo v pulzih DD."""
    import napoved as model
    poskusi, vezja, zasnove = [], [], {}
    for z_ime, n, dd in tocke:
        if (z_ime, n) not in zasnove:
            z = ghz.zasnova_za(backend, z_ime, n)
            zasnove[(z_ime, n)] = (z, kakovost_kubitov(backend, z.postavitev), model.napoved(backend, z_ime, n))
        z, kakovost, napoved_ = zasnove[(z_ime, n)]
        f = ghz.faze(n, stevilo_faz)
        logicna = [ghz.vezje_populacija(z.priprava)] + [ghz.vezje_pariteta(z.priprava, x) for x in f]
        isa = ghz.prevedi(logicna, backend, z.postavitev, dd=dd)
        for qc in isa:
            if st_dvokubitnih(qc) != n - 1:
                raise RuntimeError(f"{qc.name}: prevajalnik je dodal vrata ({st_dvokubitnih(qc)} namesto {n - 1})")
            if merjeni_kubiti(qc) != dict(enumerate(z.postavitev)):
                raise RuntimeError(f"{qc.name}: meritve niso na izbranih kubitih")
        poskusi.append({"zasnova": z_ime, "n": n, "dd": dd, "postavitev": z.postavitev, "faze": f,
                        "zacetek": 2 * ponovitve_kal + len(vezja), "st_vezij": len(isa), "kakovost": kakovost,
                        "napoved": {k: napoved_[k] for k in ("F_sur", "F_ubl", "G", "D", "A1")},
                        "lastnosti_pred": ghz.lastnosti(logicna[0]),
                        "lastnosti_po": ghz.lastnosti(isa[0], backend.target),
                        "lastnosti_po_fazno": ghz.lastnosti(isa[1], backend.target)})
        vezja += isa
    unija = sorted({q for p in poskusi for q in p["postavitev"]})
    kal0, kal1 = prevedi_za_procesor(ghz.vezja_kalibracije(len(unija)), backend, unija)
    for qc in (kal0, kal1):
        if merjeni_kubiti(qc) != dict(enumerate(unija)):
            raise RuntimeError("kalibracijsko vezje ne meri izbranih kubitov")
    return ({"dd": "v vezju", "unija": unija, "poskusi": poskusi, "ponovitve_kal": ponovitve_kal},
            [kal0] * ponovitve_kal + [kal1] * ponovitve_kal + vezja)


def ponovitve_kalibracije(a):
    return max(1, round(a.shots_kal / a.shots))


def posnetkov_posla(vezja, a):
    return len(vezja) * a.shots


def izpisi_nacrt(posli, a, poraba):
    print(f"{'DD':<4}{'zasnova':<8}{'N':>4}  {'globina':>8} {'2q':>4} {'trajanje':>10}  {'branje':>7} {'2q napaka':>9} "
          f"{'T2 [us]':>8}  {'model F sur/ubl':>15}")
    posnetkov = 0
    for opis, vezja in posli:
        for p in opis["poskusi"]:
            lp, k, m = p["lastnosti_po_fazno"], p["kakovost"], p["napoved"]
            print(f"{'da' if p['dd'] else 'ne':<4}{p['zasnova']:<8}{p['n']:>4}  {lp['globina']:>8} {lp['dvokubitna']:>4} "
                  f"{(lp['trajanje_us'] or 0):>8.2f}us  {k['branje']:>7.4f} {k['dvokubitna']:>9.4f} {k['t2_us']:>8.0f}  "
                  f"{m['F_sur']:>7.3f}/{m['F_ubl']:.3f}")
        posnetkov += posnetkov_posla(vezja, a)
    st_vezij = sum(len(v) for _, v in posli)
    ocena = ocena_casa(len(posli), posnetkov)
    preostalo = poraba.get("usage_remaining_seconds")
    r = ponovitve_kalibracije(a)
    print(f"\nposli: {len(posli)}, vezja: {st_vezij} (vsa po {a.shots} posnetkov; kalibracija 2 x {r} vezij = {r * a.shots} posnetkov na stanje)")
    print(f"ocena porabe: {ocena:.1f} s  (= {CAS_POSEL_S:g} s x {len(posli)} + {CAS_POSNETEK_S * 1e3:g} ms x {posnetkov} posnetkov)")
    print(f"preostanek na instanci: {preostalo if preostalo is not None else '? (lokalno)'} s;  meja: {a.max_sekund or '-'} s")
    return ocena


def shrani(ime, podatki):
    IZHOD.mkdir(parents=True, exist_ok=True)
    pot = IZHOD / f"{ime}.json"
    pot.write_text(json.dumps(podatki, indent=1, ensure_ascii=False))
    return pot


def beri(ime):
    pot = IZHOD / f"{ime}.json"
    if not pot.exists():
        sys.exit(f"Ni datoteke {pot}.")
    return json.loads(pot.read_text())


def omejitev_posla(a, ocena_posla):
    """Najdaljši dovoljeni čas posla (max_execution_time): faktor x ocena + 3 s. Tolikšen del meje posel rezervira."""
    c = int(math.ceil(a.faktor_omejitve * ocena_posla + 3))
    if c < max(1, ocena_posla):
        sys.exit(f"Omejitev posla {c} s je manjša od ocene {ocena_posla:.1f} s: preveri --faktor-omejitve in model.")
    return c


def ocena_ibm(service, job_id, cakaj_s=90, korak_s=5):
    """IBM-ova ocena trajanja posla (quantum_seconds); vsakič nov objekt posla, ker se prva prazna ocena ne osveži."""
    konec = time.time() + cakaj_s
    while time.time() < konec:
        try:
            q = service.job(job_id).usage_estimation.get("quantum_seconds")
            if q is not None:
                return float(q)
        except Exception:  # noqa: BLE001
            pass
        time.sleep(korak_s)
    return None


def dejanska_poraba(job, cakaj_s=240, korak_s=10):
    """Obračunani čas posla. Takoj po koncu je obračun še "pending" in job.usage() vrne 0, zato počakamo."""
    konec = time.time() + cakaj_s
    while time.time() < konec:
        try:
            if job.metrics().get("usage", {}).get("status", "pending") != "pending":
                return float(job.usage())
        except Exception:  # noqa: BLE001
            pass
        time.sleep(korak_s)
    return None


def poslji(a, service, backend, poraba, posli, ocena):
    """Zaporedna oddaja poslov znotraj meje a.max_sekund.

    Pravilo rezervacije: pred oddajo posel rezervira svojo celotno omejitev (max_execution_time), vsota rezervacij
    nikoli ne preseže meje. Neporabljeni del se sprosti šele, ko je dejanska poraba obračunana; če obračuna ni,
    ostane rezervirana cela omejitev. Tako skupna poraba ne more preseči meje, ne glede na oceno."""
    if not a.max_sekund:
        sys.exit("Za oddajo je obvezna meja --max-sekund (dogovorjeni skupni procesorski čas).")
    if not a.fake:
        preostalo = poraba.get("usage_remaining_seconds")
        if poraba.get("usage_limit_reached") or preostalo is None:
            sys.exit("Omejitev porabe je dosežena ali preostanka ni mogoče prebrati: nič ni poslano.")
        if a.max_sekund > preostalo:
            sys.exit(f"Meja {a.max_sekund} s presega preostanek {preostalo} s: nič ni poslano.")
        neobracunani = [z["job_id"] for z in beri_dnevnik() if z.get("ime_poskusa") and not z.get("fake")
                        and z.get("porabljen_cas_s") is None]
        if neobracunani:
            sys.exit(f"Posli brez obračuna ({', '.join(neobracunani)}): najprej `prevzemi`, da se poraba zapiše; nič ni poslano.")
        if (IZHOD / f"{a.ime}.json").exists():
            sys.exit(f"rezultati/qpu/{a.ime}.json že obstaja (zapis plačanega zagona): izberi drugo --ime.")
    if a.max_poslov and len(posli) > a.max_poslov:
        sys.exit(f"Načrt ima {len(posli)} poslov, odobrenih je {a.max_poslov}: nič ni poslano.")

    podatki = {"ime": a.ime, "backend": backend.name, "fake": a.fake, "shots": a.shots, "shots_kal": a.shots_kal,
               "stevilo_faz": a.faze, "brez_kubitov": a.brez_kubitov,
               "max_sekund": a.max_sekund, "odobritev": a.odobritev, "model_posnetek_ms": CAS_POSNETEK_S * 1e3,
               "faktor_omejitve": a.faktor_omejitve, "posli": []}
    rezervirano = 0.0
    for opis, vezja in posli:
        ocena_posla = ocena_casa(1, posnetkov_posla(vezja, a))
        omejitev = omejitev_posla(a, ocena_posla)
        if rezervirano + omejitev > a.max_sekund:
            print(f"Ustavljeno pred poslom: rezervirano {rezervirano:.0f} s + omejitev {omejitev} s > meja {a.max_sekund} s.")
            break
        zapis = {**opis, "ocena_s": round(ocena_posla, 2), "max_execution_time": omejitev, "job_id": None,
                 "ocena_ibm_s": None, "poraba_s": None, "stanje": None, "imena_vezij": [qc.name for qc in vezja],
                 "stetja": None, "cas_oddaje": datetime.now(timezone.utc).isoformat(timespec="seconds")}
        podatki["posli"].append(zapis)
        if a.fake:
            sim = ghz.simulator(backend)
            zapis["stetja"] = sim.pozeni(vezja, a.shots)
            zapis["job_id"], zapis["stanje"] = f"lokalno-{len(podatki['posli'])}", "DONE"
            shrani(a.ime, podatki)
            continue

        from qiskit_ibm_runtime import SamplerV2 as Sampler
        moznosti = {"default_shots": a.shots, "max_execution_time": omejitev,
                    "environment": {"job_tags": [OZNAKA, a.ime]}}  # DD je že v vezjih; storitev ga ne doda
        rezervirano += omejitev
        job = Sampler(mode=backend, options=moznosti).run(vezja, shots=a.shots)
        zapis["job_id"] = job.job_id()
        # takoj zapišemo job ID (dnevnik in datoteka), šele nato karkoli drugega
        dodaj_v_dnevnik({"cas": zapis["cas_oddaje"], "job_id": job.job_id(), "backend": backend.name, "fake": False,
                         "shots": a.shots, "shots_kal": a.shots_kal, "dd": "v vezju", "ime_poskusa": a.ime, "max_sekund": omejitev,
                         "ocena_cas_s": zapis["ocena_s"], "ocena_ibm_s": None,
                         "postavitve": {f"{p['zasnova']}_{p['n']}": p["postavitev"] for p in opis["poskusi"]},
                         "kalibracija_kubiti": opis["unija"],
                         "vezja": [{"ime": qc.name, "kubitov": qc.num_qubits, "globina_isa": qc.depth(),
                                    "dvokubitna_isa": st_dvokubitnih(qc), "stetje": None} for qc in vezja],
                         "porabljen_cas_s": None})
        shrani(a.ime, podatki)
        print(f"posel {job.job_id()}, omejitev {omejitev} s, "
              f"rezervirano {rezervirano:.0f} s od {a.max_sekund} s", flush=True)

        zapis["ocena_ibm_s"] = ocena_ibm(service, job.job_id())
        shrani(a.ime, podatki)
        if zapis["ocena_ibm_s"] is not None and zapis["ocena_ibm_s"] > omejitev:
            job.cancel()
            zapis["stanje"] = "CANCELLED (ocena IBM nad omejitvijo)"
            shrani(a.ime, podatki)
            sys.exit(f"Ocena IBM {zapis['ocena_ibm_s']} s presega omejitev {omejitev} s: posel preklican, ustavljeno.")
        try:
            rezultat = job.result()
        except Exception as e:  # noqa: BLE001  (neuspel ali preklican posel: omejitev ostane rezervirana)
            zapis["stanje"] = f"NAPAKA: {e}"
            shrani(a.ime, podatki)
            sys.exit(f"Posel {job.job_id()} ni uspel ({e}); ustavljeno, nič več ni poslano.")
        zapis["stetja"], zapis["stanje"] = stetja_iz_rezultata(rezultat), "DONE"
        shrani(a.ime, podatki)
        zapis["poraba_s"] = dejanska_poraba(job)
        dopolni_zapis(job.job_id(), rezultat, zapis["poraba_s"])
        if zapis["poraba_s"] is not None:
            rezervirano += zapis["poraba_s"] - omejitev  # tudi poraba nad omejitvijo se šteje
        print(f"  končano: obračunano {zapis['poraba_s']} s (ocena {ocena_posla:.1f} s, IBM {zapis['ocena_ibm_s']} s); "
              f"rezervirano {rezervirano:.0f} s od {a.max_sekund} s", flush=True)
        shrani(a.ime, podatki)
    podatki["rezervirano_s"] = rezervirano
    print(f"shranjeno: {shrani(a.ime, podatki)}")
    return podatki


def prevzemi(a, service):
    """Izidi in obračun za posle brez izidov; neuspel posel zapiše in nadaljuje z ostalimi."""
    podatki = beri(a.ime)
    for zapis in podatki["posli"]:
        if not zapis["job_id"] or str(zapis["job_id"]).startswith("lokalno"):
            continue
        job = service.job(zapis["job_id"])
        if zapis["stetja"] is None:
            try:
                rezultat = job.result()
                zapis["stetja"], zapis["stanje"] = stetja_iz_rezultata(rezultat), "DONE"
            except Exception as e:  # noqa: BLE001
                zapis["stanje"] = f"NAPAKA: {e}"
                rezultat = None
        else:
            rezultat = None
        if zapis.get("poraba_s") is None:
            zapis["poraba_s"] = dejanska_poraba(job, cakaj_s=30)
        if rezultat is not None or zapis["poraba_s"] is not None:
            try:
                dopolni_zapis(zapis["job_id"], rezultat if rezultat is not None else job.result(), zapis["poraba_s"])
            except Exception:  # noqa: BLE001  (neuspel posel: poraba ostane v datoteki poskusa)
                pass
        shrani(a.ime, podatki)
    return podatki


def _marginala(stetje, indeksi, k):
    """Števila izidov samo za kubite na mestih `indeksi` (od k kubitov kalibracije), v njihovem vrstnem redu."""
    novo = {}
    for niz, st in stetje.items():
        kljuc = "".join(niz[k - 1 - i] for i in reversed(indeksi))
        novo[kljuc] = novo.get(kljuc, 0) + st
    return novo


def analiza(podatki, zankanje=200):
    vrstice = []
    for zapis in podatki["posli"]:
        if not zapis["stetja"]:
            continue
        k = len(zapis["unija"])
        r = zapis.get("ponovitve_kal", 1)
        kal0, kal1 = {}, {}
        for skupno, stetja_kal in ((kal0, zapis["stetja"][:r]), (kal1, zapis["stetja"][r:2 * r])):
            for stetje in stetja_kal:
                for niz, st in stetje.items():
                    skupno[niz] = skupno.get(niz, 0) + st
        for p in zapis["poskusi"]:
            indeksi = [zapis["unija"].index(q) for q in p["postavitev"]]
            stetja = ([_marginala(kal0, indeksi, k), _marginala(kal1, indeksi, k)]
                      + zapis["stetja"][p["zacetek"]:p["zacetek"] + p["st_vezij"]])
            surovo = ghz.zvestoba(stetja, p["n"], "pariteta", p["faze"], ublazitev=False, zankanje=zankanje)
            ublazeno = ghz.zvestoba(stetja, p["n"], "pariteta", p["faze"], ublazitev=True, zankanje=zankanje)
            vrstice.append({"dd": p.get("dd", zapis["dd"]), "zasnova": p["zasnova"], "n": p["n"], "job_id": zapis["job_id"],
                            "kakovost": p.get("kakovost"), "napoved": p.get("napoved"),
                            "postavitev": p["postavitev"], "lastnosti_po_fazno": p["lastnosti_po_fazno"],
                            "surovo": surovo, "ublazeno": ublazeno})
            s, u = surovo, ublazeno
            m = p.get("napoved") or {}
            print(f"DD={'da' if p.get('dd', zapis['dd']) else 'ne'} {p['zasnova']:<7} N={p['n']:>3} | surovo F={s['F']:.3f}±{s['sigma_F']:.3f} "
                  f"(P={s['P']:.3f}, C={s['C']:.3f}) | ublaženo F={u['F']:.3f}±{u['sigma_F']:.3f} | model "
                  f"{m.get('F_sur', float('nan')):.3f}/{m.get('F_ubl', float('nan')):.3f}", flush=True)
    return vrstice


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("ukaz", choices=["nacrt", "poslji", "prevzemi", "analiza"])
    ap.add_argument("--ime", required=True, help="ime poskusa (rezultati/qpu/<ime>.json)")
    ap.add_argument("--backend", default="ibm_fez")
    ap.add_argument("--zasnove", nargs="+", choices=["veriga", "drevo"], default=["veriga", "drevo"])
    ap.add_argument("--n", type=int, nargs="+", default=[5, 20], help="N za obe zasnovi (če ni --n-veriga/--n-drevo)")
    ap.add_argument("--n-veriga", type=int, nargs="+", default=None)
    ap.add_argument("--n-drevo", type=int, nargs="+", default=None)
    ap.add_argument("--shots-kal", type=int, default=4000, help="posnetki za kalibracijski vezji (ublažitev branja)")
    ap.add_argument("--faze", type=int, default=9, help="število faz na pol kroga (N ne sme biti večkratnik)")
    ap.add_argument("--dd", choices=["brez", "z", "oboje"], default="brez")
    ap.add_argument("--brez-kubitov", type=int, nargs="+", default=[],
                    help="kubiti, ki jih izbira ne sme uporabiti (slabi po meritvi iz prejšnjega posla)")
    ap.add_argument("--shots", type=int, default=1000)
    ap.add_argument("--max-sekund", type=float, default=None, help="skupna meja porabe, dogovorjena pred zagonom")
    ap.add_argument("--max-poslov", type=int, default=None, help="največ poslov, dogovorjeno pred zagonom")
    ap.add_argument("--faktor-omejitve", type=float, default=2.0,
                    help="omejitev posla = faktor x ocena + 3 s (2 dokler model ni preverjen s pilotom)")
    ap.add_argument("--model-posnetek-ms", type=float, default=None,
                    help="izmerjen čas na posnetek [ms] (iz pilota), namesto privzetih 0,35 ms")
    ap.add_argument("--odobritev", default=None, help="kratek zapis odobritve (kdo, kdaj, meja) za dnevnik")
    ap.add_argument("--fake", action="store_true", help="lokalno: FakeFez in šumni simulator, brez procesorja")
    a = ap.parse_args()
    ghz.IZKLJUCENI_KUBITI = set(a.brez_kubitov)
    if a.faktor_omejitve < 1:
        ap.error("--faktor-omejitve mora biti vsaj 1")
    if a.model_posnetek_ms is not None and a.model_posnetek_ms <= 0:
        ap.error("--model-posnetek-ms mora biti pozitiven")
    if a.model_posnetek_ms:
        global CAS_POSNETEK_S
        CAS_POSNETEK_S = a.model_posnetek_ms / 1e3

    if a.ukaz == "analiza":
        podatki = beri(a.ime)
        vrstice = analiza(podatki)
        pot = shrani(f"{a.ime}_analiza", {"ime": a.ime, "backend": podatki["backend"], "shots": podatki["shots"],
                                          "rezultati": vrstice})
        print(f"shranjeno: {pot.relative_to(KOREN)}")
        return
    service, backend, poraba = povezava(a.backend, a.fake)
    if a.ukaz == "prevzemi":
        analiza(prevzemi(a, service))
        return
    if not a.fake:
        st = backend.status()
        print(f"procesor {backend.name}: deluje={st.operational}, v vrsti={st.pending_jobs}")
        if not st.operational:
            sys.exit("Procesor ne deluje: nič ni poslano.")
    nastavitve = {"brez": [False], "z": [True], "oboje": [False, True]}[a.dd]
    n_po_zasnovi = {"veriga": a.n_veriga or a.n, "drevo": a.n_drevo or a.n}
    tocke = [(z, n, dd) for z in a.zasnove for n in n_po_zasnovi[z] for dd in nastavitve]
    posli = [zgradi_posel(backend, tocke, a.faze, ponovitve_kalibracije(a))]
    ocena = izpisi_nacrt(posli, a, poraba)
    if a.ukaz == "nacrt":
        print("\nnacrt: nič ni bilo poslano.")
        return
    t0 = time.time()
    podatki = poslji(a, service, backend, poraba, posli, ocena)
    print(f"čas: {time.time() - t0:.0f} s")
    analiza(podatki)


if __name__ == "__main__":
    main()
