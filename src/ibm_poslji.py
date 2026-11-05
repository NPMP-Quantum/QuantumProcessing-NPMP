"""Oddaja posla (ene naloge z več vezji) na izbran procesor IBM, s predhodnim pregledom in potrditvijo.

Vsak zagon najprej izpiše stanje računa in procesorja (ibm_status.py), nato načrt oddaje: vezja pred
prevajanjem in po njem ter oceno procesorskega časa v primerjavi s preostankom na instanci.
Brez --poslji se nič ne pošlje. Z --poslji je obvezna meja --max-sekund (IBM posel prekine, ko jo preseže),
oddajo pa je treba potrditi z imenom procesorja v terminalu (brez terminala se program ne izvede).

Primeri:
  python src/ibm_poslji.py --backend ibm_fez --ghz 5 10                    # samo načrt in ocena
  python src/ibm_poslji.py --backend ibm_fez --ghz 5 10 --shots 1000 --max-sekund 10 --poslji
  python src/ibm_poslji.py --backend ibm_fez --qasm a.qasm b.qasm --max-sekund 20 --poslji
  python src/ibm_poslji.py --fake --ghz 5 --poslji                         # lokalni šumni simulator
Izide nalog, ki jih ni bilo mogoče počakati: python src/ibm_status.py naloga <job_id> --izidi
"""

import argparse
import math
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

from qiskit import QuantumCircuit, qasm2, qasm3
from qiskit.transpiler import generate_preset_pass_manager
from qiskit_ibm_runtime import SamplerV2 as Sampler

import ibm_status
from ibm_skupno import dodaj_v_dnevnik, dopolni_zapis, nalozi_env, povezi, st_dvokubitnih

# model porabe iz poročila (enačba g20:eq:cas): t = 2 s * posli + 0,35 ms * vezja * posnetki
CAS_POSEL_S = 2.0
CAS_POSNETEK_S = 0.35e-3
OZNAKA = "skupina20"


def ghz_linearno(n):
    qc = QuantumCircuit(n, name=f"ghz_lin_{n}")
    qc.h(0)
    for i in range(n - 1):
        qc.cx(i, i + 1)
    qc.measure_all()
    return qc


def preberi_qasm(pot):
    besedilo = Path(pot).read_text()
    qc = qasm2.loads(besedilo) if besedilo.lstrip().startswith("OPENQASM 2") else qasm3.loads(besedilo)
    qc.name = Path(pot).stem
    return qc


def ocena_casa(st_vezij, shots):
    return CAS_POSEL_S + CAS_POSNETEK_S * st_vezij * shots


def p_ghz(stetje):
    n = len(next(iter(stetje)))
    return (stetje.get("0" * n, 0) + stetje.get("1" * n, 0)) / sum(stetje.values())


def izpisi_nacrt(vezja, isa, shots):
    print("== Načrt oddaje ==")
    print(f"  vezij: {len(vezja)}  posnetkov na vezje: {shots}  poslov: 1")
    print(f"  {'vezje':<16}{'kubitov':>8}{'globina':>9}{'2q-vrat':>9}   po prevajanju:{'globina':>9}{'2q-vrat':>9}")
    for qc, v in zip(vezja, isa):
        print(f"  {qc.name:<16}{qc.num_qubits:>8}{qc.depth():>9}{st_dvokubitnih(qc):>9}"
              f"   {'':<14}{v.depth():>9}{st_dvokubitnih(v):>9}")


def izpisi_oceno(ocena, n_vezij, shots, poraba, max_sekund):
    print("== Ocena procesorskega časa ==")
    print(f"  ocena: {CAS_POSEL_S:g} s + {CAS_POSNETEK_S * 1e3:g} ms * {n_vezij} * {shots} = {ocena:.2f} s")
    preostalo = poraba.get("usage_remaining_seconds")
    if preostalo is None:
        print("  preostalo na instanci: ni podatka")
    else:
        print(f"  preostalo na instanci: {preostalo:g} s   po oddaji (po oceni): {preostalo - ocena:.2f} s")
    if max_sekund:
        najslabsi = f"{preostalo - max_sekund:g} s" if preostalo is not None else "?"
        print(f"  meja --max-sekund: {max_sekund} s (IBM posel prekine ob preseganju); po oddaji v najslabšem primeru: {najslabsi}")
    else:
        print(f"  predlagana meja --max-sekund: {max(math.ceil(1.5 * ocena), math.ceil(ocena) + 1)} s")


def razlogi_zavrnitve(p, ocena, max_sekund, poraba, fake):
    razlogi = []
    if not p["deluje"]:
        razlogi.append(f"procesor {p['ime']} ne deluje ({p['sporocilo']})")
    if not fake:
        preostalo = poraba.get("usage_remaining_seconds")
        if poraba.get("usage_limit_reached"):
            razlogi.append("omejitev porabe na instanci je dosežena")
        if preostalo is None:
            razlogi.append("preostanka procesorskega časa ni bilo mogoče prebrati")
        else:
            if ocena > preostalo:
                razlogi.append(f"ocena {ocena:.2f} s presega preostanek {preostalo:g} s")
            if max_sekund and max_sekund > preostalo:
                razlogi.append(f"meja {max_sekund} s presega preostanek {preostalo:g} s")
    if max_sekund and ocena > max_sekund:
        razlogi.append(f"ocena {ocena:.2f} s presega mejo {max_sekund} s")
    return razlogi


def izpisi_izide(vezja, stetja):
    for qc, stetje in zip(vezja, stetja):
        najpogostejsi = sorted(stetje.items(), key=lambda kv: -kv[1])[:6]
        vrstica = f"  {qc.name}: {najpogostejsi}"
        if qc.name.startswith("ghz"):
            vrstica += f"  P(GHZ) = {p_ghz(stetje):.3f}"
        print(vrstica)


def izvedi(vezja, backend_ime, shots=1000, max_sekund=None, opt=1, poslji=False, fake=False, cakaj=True):
    """Pregled stanja, načrt, ocena in (po potrditvi) oddaja vezij v enem poslu."""
    if poslji and not max_sekund:
        sys.exit("Za oddajo je obvezna meja --max-sekund (procesorski čas v sekundah).")
    if poslji and not fake and not (sys.stdin.isatty() and sys.stdout.isatty()):
        sys.exit("Oddaja zahteva potrditev v terminalu; program zaženite sami, ne prek skripte.")

    if fake:
        from qiskit_ibm_runtime.fake_provider import FakeFez

        backend, poraba = FakeFez(), {}
        print("== Lokalni šumni model FakeFez (brez omrežja, brez porabe) ==")
    else:
        service = povezi()
        poraba = ibm_status.pregled(service, limit=5)
        backend = service.backend(backend_ime)
    procesor = ibm_status.povzetek_procesorja(backend)
    ibm_status.izpisi_procesor(procesor)

    isa = [generate_preset_pass_manager(backend=backend, optimization_level=opt).run(qc) for qc in vezja]
    izpisi_nacrt(vezja, isa, shots)
    ocena = ocena_casa(len(vezja), shots)
    izpisi_oceno(ocena, len(vezja), shots, poraba, max_sekund)
    razlogi = razlogi_zavrnitve(procesor, ocena, max_sekund, poraba, fake)
    print("  ustreza: " + ("da" if not razlogi else "NE, " + "; ".join(razlogi)))

    if not poslji:
        print("\nBrez --poslji: nič ni bilo poslano.")
        return
    if razlogi:
        sys.exit("Oddaja zavrnjena.")
    if not fake:
        print("\nOddaja porabi procesorski čas instance in je ni mogoče razveljaviti.")
        if input(f"Za oddajo vpišite ime procesorja ({backend.name}); karkoli drugega prekliče: ").strip() != backend.name:
            sys.exit("Preklicano, nič ni bilo poslano.")

    moznosti = {"max_execution_time": max_sekund, "environment": {"job_tags": [OZNAKA]}}
    t0 = time.time()
    job = Sampler(mode=backend, options=moznosti).run(isa, shots=shots)
    job_id = job.job_id()
    print(f"\nNaloga poslana: job ID = {job_id}")
    zapis = {
        "cas": datetime.now(timezone.utc).isoformat(),
        "job_id": job_id,
        "backend": backend.name,
        "fake": fake,
        "shots": shots,
        "opt": opt,
        "max_sekund": max_sekund,
        "ocena_cas_s": round(ocena, 3),
        "ocena_ibm_s": None,
        "stanje_ob_oddaji": {
            "v_vrsti": procesor["v_vrsti"],
            "preostalo_s": poraba.get("usage_remaining_seconds"),
            "kalibracija": procesor["kalibracija"],
        },
        "vezja": [
            {"ime": qc.name, "kubitov": qc.num_qubits, "globina": qc.depth(), "dvokubitna": st_dvokubitnih(qc),
             "globina_isa": v.depth(), "dvokubitna_isa": st_dvokubitnih(v), "stetje": None}
            for qc, v in zip(vezja, isa)
        ],
        "porabljen_cas_s": None,
    }
    try:
        zapis["ocena_ibm_s"] = job.usage_estimation.get("quantum_seconds")
    except Exception:  # noqa: BLE001
        pass
    dodaj_v_dnevnik(zapis)

    if zapis["ocena_ibm_s"] is not None:
        print(f"  ocena IBM: {zapis['ocena_ibm_s']} s")
        if zapis["ocena_ibm_s"] > max_sekund:
            job.cancel()
            sys.exit(f"Ocena IBM presega mejo {max_sekund} s: naloga {job_id} preklicana. Ponovite z večjo mejo.")
    if not cakaj:
        print(f"  ne čakam na izide; pozneje: python src/ibm_status.py naloga {job_id} --izidi")
        return

    print("  čakam na izide (Ctrl-C prekine samo čakanje, naloga teče naprej) ...")
    try:
        rezultat = job.result()
    except KeyboardInterrupt:
        sys.exit(f"\nČakanje prekinjeno. Naloga {job_id} teče naprej; izidi: python src/ibm_status.py naloga {job_id} --izidi")
    print(f"  čas od oddaje do izidov: {time.time() - t0:.1f} s")
    poraba_s = job.usage() or None
    zapis = dopolni_zapis(job_id, rezultat, poraba_s)
    izpisi_izide(vezja, [v["stetje"] for v in zapis["vezja"]])
    if poraba_s:
        print(f"  porabljen čas procesorja: {poraba_s} s")
    elif not fake:
        print(f"  poraba še ni obračunana; pozneje: python src/ibm_status.py naloga {job_id}")
    print("  zapisano v rezultati/naloge.jsonl")


def main():
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--backend", help="ime procesorja (obvezno, razen z --fake)")
    p.add_argument("--ghz", type=int, nargs="+", default=[], metavar="N", help="linearna GHZ vezja z N kubiti")
    p.add_argument("--qasm", nargs="+", default=[], metavar="DATOTEKA", help="vezja v OpenQASM (z meritvami)")
    p.add_argument("--shots", type=int, default=1000)
    p.add_argument("--max-sekund", type=int, help="meja procesorskega časa v sekundah (obvezna z --poslji)")
    p.add_argument("--opt", type=int, default=1, choices=range(4), help="stopnja optimizacije prevajanja")
    p.add_argument("--poslji", action="store_true", help="po potrditvi dejansko oddaj posel")
    p.add_argument("--ne-cakaj", action="store_true", help="po oddaji ne čakaj na izide")
    p.add_argument("--fake", action="store_true", help="lokalni šumni model FakeFez namesto IBM")
    args = p.parse_args()
    if not (args.fake or args.backend):
        p.error("podajte --backend (ali --fake)")

    nalozi_env()
    vezja = [ghz_linearno(n) for n in args.ghz] + [preberi_qasm(f) for f in args.qasm]
    if not vezja:
        p.error("podajte vsaj eno vezje (--ghz ali --qasm)")
    if any(qc.num_clbits == 0 for qc in vezja):
        p.error("vsa vezja morajo imeti meritve")
    izvedi(vezja, args.backend, args.shots, args.max_sekund, args.opt, args.poslji, args.fake, not args.ne_cakaj)


if __name__ == "__main__":
    main()
