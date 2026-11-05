"""Pregled stanja na IBM Quantum Platform: račun in poraba, procesorji, zadnje naloge, podrobnosti naloge.

Samo bere: ne pošlje nič in ne porabi procesorskega časa. ibm_poslji.py ga pokliče pred vsako oddajo.

Primeri:
  python src/ibm_status.py                          # račun, poraba, procesorji, zadnje naloge
  python src/ibm_status.py --limit 30               # več zadnjih nalog
  python src/ibm_status.py procesor ibm_fez         # lastnosti in kalibracija procesorja
  python src/ibm_status.py naloga <job_id>          # podrobnosti naloge
  python src/ibm_status.py naloga <job_id> --izidi  # še izidi (dopolnijo rezultati/naloge.jsonl)
  python src/ibm_status.py --fake procesor          # lokalni model FakeFez, brez omrežja
"""

import argparse
import statistics
from datetime import datetime

from ibm_skupno import dopolni_zapis, nalozi_env, povezi, stetja_iz_rezultata

OZNAKE_PORABE = {
    "usage_consumed_seconds": "porabljeno [s]",
    "usage_limit_seconds": "omejitev [s]",
    "usage_allocation_seconds": "dodeljeno [s]",
    "usage_remaining_seconds": "preostalo [s]",
    "usage_limit_reached": "omejitev dosežena",
}


def cas(dt):
    return dt.strftime("%Y-%m-%d %H:%M:%S") if dt else "?"


def izpisi_racun(service):
    print("== Račun ==")
    try:
        aktivna = service.active_instance()
        for inst in service.instances():
            znak = "*" if inst.get("crn") == aktivna else " "
            print(f" {znak} instanca: {inst.get('name')}  plan: {inst.get('plan')}  crn: {inst.get('crn')}")
    except Exception as e:  # noqa: BLE001
        print(f"  (instanc ni bilo mogoče prebrati: {e})")
    try:
        poraba = service.usage()
    except Exception as e:  # noqa: BLE001
        print(f"  (porabe ni bilo mogoče prebrati: {e})")
        return {}
    for kljuc, vrednost in poraba.items():
        print(f"  {OZNAKE_PORABE.get(kljuc, kljuc)}: {vrednost}")
    return poraba


def izpisi_procesorje(service):
    print("== Procesorji ==")
    for b in service.backends(simulator=False):
        try:
            st = b.status()
            print(f"  {b.name:<16} kubitov={b.num_qubits:<4} deluje={st.operational!s:<5} v_vrsti={st.pending_jobs}")
        except Exception as e:  # noqa: BLE001
            print(f"  {b.name:<16} (status ni dosegljiv: {e})")


def ime_stanja(job):
    """job.status() vrne niz (novejši qiskit-ibm-runtime) ali enum (starejši)."""
    stanje = job.status()
    return getattr(stanje, "name", stanje)


def izpisi_naloge(service, limit):
    print(f"== Zadnje naloge (največ {limit}) ==")
    for job in service.jobs(limit=limit):
        try:
            stanje = ime_stanja(job)
            backend = job.backend()
            poraba = job.metrics().get("usage", {})
            if poraba.get("status", "pending") != "pending":
                poraba_s = f"{poraba.get('qpu_charge_time_seconds')} s"
            else:
                poraba_s = "obračun v teku" if job.in_final_state() else "-"
            print(f"  {job.job_id()}  {backend.name if backend else '?':<14} {stanje:<10} "
                  f"{cas(job.creation_date)}  poraba: {poraba_s}")
        except Exception as e:  # noqa: BLE001
            print(f"  {job.job_id()}  (podrobnosti niso dosegljive: {e})")


def pregled(service, limit=10):
    """Račun, procesorji in zadnje naloge. Vrne slovar porabe (za ibm_poslji.py)."""
    poraba = izpisi_racun(service)
    izpisi_procesorje(service)
    izpisi_naloge(service, limit)
    return poraba


def mediana_napake(target, ime):
    napake = [p.error for p in target[ime].values() if p is not None and p.error is not None]
    return statistics.median(napake) if napake else None


def povzetek_procesorja(backend):
    """Stanje, konfiguracija in mediane kalibracijskih podatkov procesorja."""
    st = backend.status()
    konf = backend.configuration()
    target = backend.target
    lastnosti =[q for q in (target.qubit_properties or []) if q is not None]
    t1 = [q.t1 for q in lastnosti if q.t1]
    t2 = [q.t2 for q in lastnosti if q.t2]
    vrata_2q = sorted(op.name for op in target.operations if getattr(op, "num_qubits", None) == 2)
    kalibracija, okvarjeni = None, []
    try:
        lastnosti_ibm = backend.properties()
        kalibracija = lastnosti_ibm.last_update_date
        okvarjeni = lastnosti_ibm.faulty_qubits()
    except Exception:  # noqa: BLE001
        pass
    return {
        "ime": backend.name,
        "kubitov": backend.num_qubits,
        "deluje": st.operational,
        "v_vrsti": st.pending_jobs,
        "sporocilo": st.status_msg,
        "procesor": getattr(konf, "processor_type", None),
        "vrata": sorted(konf.basis_gates),
        "vrata_2q": vrata_2q,
        "kalibracija": kalibracija.isoformat() if kalibracija else None,
        "t1_us": statistics.median(t1) * 1e6 if t1 else None,
        "t2_us": statistics.median(t2) * 1e6 if t2 else None,
        "napaka_branja": mediana_napake(target, "measure"),
        "napaka_sx": mediana_napake(target, "sx"),
        "napaka_2q": {v: mediana_napake(target, v) for v in vrata_2q},
        "okvarjeni": okvarjeni,
    }


def izpisi_procesor(p):
    def fmt(x, oblika):
        return "?" if x is None else format(x, oblika)

    print(f"== Procesor {p['ime']} ==")
    print(f"  kubitov: {p['kubitov']}  tip: {p['procesor']}  deluje: {p['deluje']} ({p['sporocilo']})")
    print(f"  v vrsti: {p['v_vrsti']} nalog")
    print(f"  osnovna vrata: {', '.join(p['vrata'])}  (dvokubitna: {', '.join(p['vrata_2q'])})")
    print(f"  zadnja kalibracija: {p['kalibracija'] or '?'}")
    print(f"  mediana T1: {fmt(p['t1_us'], '.1f')} us   T2: {fmt(p['t2_us'], '.1f')} us")
    print(f"  mediana napake: branje {fmt(p['napaka_branja'], '.2e')}   sx {fmt(p['napaka_sx'], '.2e')}   "
          + "   ".join(f"{v} {fmt(e, '.2e')}" for v, e in p["napaka_2q"].items()))
    print(f"  okvarjeni kubiti: {p['okvarjeni'] or 'ni'}")


def izpisi_nalogo(service, job_id, izidi):
    job = service.job(job_id)
    stanje = ime_stanja(job)
    backend = job.backend()
    metrike = job.metrics()
    casi = metrike.get("timestamps", {})
    poraba = metrike.get("usage", {})
    print(f"== Naloga {job_id} ==")
    print(f"  procesor: {backend.name if backend else '?'}  stanje: {stanje}  primitiv: {job.primitive_id}")
    print(f"  oznake: {job.tags}  session: {job.session_id}")
    if stanje == "ERROR":
        print(f"  napaka: {job.error_message()}")
    for ime in ("created", "running", "finished"):
        print(f"  {ime}: {casi.get(ime, '-')}")
    if casi.get("created") and casi.get("running"):
        cakanje = datetime.fromisoformat(casi["running"]) - datetime.fromisoformat(casi["created"])
        print(f"  čakanje v vrsti: {cakanje.total_seconds():.0f} s")
    print(f"  ocena IBM: {job.usage_estimation.get('quantum_seconds')} s")
    if poraba.get("status", "pending") == "pending":
        konec = "obračun v teku, poglejte pozneje" if job.in_final_state() else "naloga še ni končana"
        print(f"  poraba: {konec}")
    else:
        print(f"  poraba: {poraba.get('qpu_charge_time_seconds')} s")
    try:
        parametri = job.inputs
        print(f"  vezij: {len(parametri.get('pubs', []))}  možnosti: {parametri.get('options')}")
    except Exception as e:  # noqa: BLE001
        print(f"  (vhodnih podatkov ni bilo mogoče prebrati: {e})")

    if not izidi:
        return
    if stanje != "DONE":
        print("  izidi še niso na voljo.")
        return
    rezultat = job.result()
    for i, stetje in enumerate(stetja_iz_rezultata(rezultat)):
        najpogostejsi = sorted(stetje.items(), key=lambda kv: -kv[1])[:6]
        print(f"  vezje {i}: {sum(stetje.values())} posnetkov, najpogostejši izidi {najpogostejsi}")
    zapis = dopolni_zapis(job_id, rezultat, poraba.get("qpu_charge_time_seconds") or None)
    print("  izidi zapisani v rezultati/naloge.jsonl." if zapis else "  naloge ni v rezultati/naloge.jsonl, izidi niso zapisani.")


def main():
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--fake", action="store_true", help="lokalni model FakeFez namesto IBM (samo ukaz procesor)")
    p.add_argument("--limit", type=int, default=10, help="število prikazanih zadnjih nalog")
    sub = p.add_subparsers(dest="ukaz")
    sub.add_parser("pregled", help="račun, poraba, procesorji, zadnje naloge (privzeto)")
    sp = sub.add_parser("procesor", help="lastnosti in kalibracija procesorja")
    sp.add_argument("ime", nargs="?", default="ibm_fez")
    sn = sub.add_parser("naloga", help="podrobnosti naloge")
    sn.add_argument("job_id")
    sn.add_argument("--izidi", action="store_true", help="izpiši in zapiši izide")
    args = p.parse_args()
    ukaz = args.ukaz or "pregled"

    nalozi_env()
    if args.fake:
        if ukaz != "procesor":
            p.error("--fake deluje samo z ukazom procesor")
        from qiskit_ibm_runtime.fake_provider import FakeFez

        izpisi_procesor(povzetek_procesorja(FakeFez()))
        return

    service = povezi()
    if ukaz == "pregled":
        pregled(service, args.limit)
    elif ukaz == "procesor":
        izpisi_procesor(povzetek_procesorja(service.backend(args.ime)))
    else:
        izpisi_nalogo(service, args.job_id, args.izidi)


if __name__ == "__main__":
    main()
