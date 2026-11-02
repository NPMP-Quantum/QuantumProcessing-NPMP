"""Preverjanje dostopa do kvantnih procesorjev IBM (Open Plan).

Skripta:
  1. se poveže v IBM Quantum Platform z žetonom iz QISKIT_IBM_TOKEN,
  2. izpiše instance, porabo časa in dostopne procesorje,
  3. sestavi 5-kubitno stanje GHZ in ga prevede za izbrani procesor
     (globina in število dvokubitnih vrat pred prevajanjem in po njem),
  4. z zastavico --run ga dejansko izvede (privzeto 1000 ponovitev)
     in zapiše identifikator naloge (job ID) v rezultati/naloge.jsonl.

Brez zastavice --run se na procesor ne pošlje nič.
Z zastavico --fake se namesto pravega procesorja uporabi lokalni šumni
model FakeFez (za preizkus skripte brez žetona in omrežja).

Primeri:
  python koda/preveri_ibm.py              # samo povezava + prevajanje
  python koda/preveri_ibm.py --run        # izvede na najmanj zasedenem procesorju
  python koda/preveri_ibm.py --run --backend ibm_fez
  python koda/preveri_ibm.py --fake --run # lokalni šumni simulator
"""

import argparse
import json
import os
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

from qiskit import QuantumCircuit
from qiskit.transpiler import generate_preset_pass_manager

KORENSKI = Path(__file__).resolve().parent.parent
REZULTATI = KORENSKI / "rezultati"


def nalozi_env():
    """Prebere .env v korenu repozitorija (če obstaja), brez dodatnih paketov."""
    pot = KORENSKI / ".env"
    if not pot.exists():
        return
    for vrstica in pot.read_text().splitlines():
        vrstica = vrstica.strip()
        if not vrstica or vrstica.startswith("#") or "=" not in vrstica:
            continue
        kljuc, vrednost = vrstica.split("=", 1)
        os.environ.setdefault(kljuc.strip(), vrednost.strip().strip('"').strip("'"))


def ghz_linearno(n):
    qc = QuantumCircuit(n, name=f"ghz_lin_{n}")
    qc.h(0)
    for i in range(n - 1):
        qc.cx(i, i + 1)
    qc.measure_all()
    return qc


def st_dvokubitnih(qc):
    return sum(1 for inst in qc.data if inst.operation.num_qubits == 2)


def povezi():
    from qiskit_ibm_runtime import QiskitRuntimeService

    token = os.environ.get("QISKIT_IBM_TOKEN")
    instance = os.environ.get("QISKIT_IBM_INSTANCE") or None
    if token:
        return QiskitRuntimeService(
            channel="ibm_quantum_platform", token=token, instance=instance
        )
    # morda je račun shranjen lokalno (QiskitRuntimeService.save_account)
    try:
        return QiskitRuntimeService()
    except Exception as e:  # noqa: BLE001
        sys.exit(
            "Ni žetona: nastavite QISKIT_IBM_TOKEN (okoljska spremenljivka ali .env).\n"
            f"Podrobnosti: {e}"
        )


def izpisi_racun(service):
    print("== Račun ==")
    try:
        for inst in service.instances():
            print(f"  instanca: {inst.get('name')}  plan: {inst.get('plan')}  crn: {inst.get('crn')}")
    except Exception as e:  # noqa: BLE001
        print(f"  (instanc ni bilo mogoče prebrati: {e})")
    try:
        poraba = service.usage()
        print(f"  poraba: {json.dumps(poraba, default=str)}")
    except Exception as e:  # noqa: BLE001
        print(f"  (porabe ni bilo mogoče prebrati: {e})")

    print("== Procesorji ==")
    for b in service.backends(simulator=False):
        try:
            st = b.status()
            print(
                f"  {b.name:<16} kubitov={b.num_qubits:<4} "
                f"deluje={st.operational!s:<5} v_vrsti={st.pending_jobs}"
            )
        except Exception as e:  # noqa: BLE001
            print(f"  {b.name:<16} (status ni dosegljiv: {e})")


def main():
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--run", action="store_true", help="dejansko izvedi vezje")
    p.add_argument("--fake", action="store_true", help="lokalni šumni model FakeFez namesto IBM")
    p.add_argument("--backend", help="ime procesorja (privzeto najmanj zaseden)")
    p.add_argument("--n", type=int, default=5, help="število kubitov GHZ (privzeto 5)")
    p.add_argument("--shots", type=int, default=1000)
    args = p.parse_args()

    nalozi_env()

    if args.fake:
        from qiskit_ibm_runtime.fake_provider import FakeFez

        backend = FakeFez()
        service = None
        print("== Lokalni šumni model FakeFez ==")
    else:
        service = povezi()
        izpisi_racun(service)
        backend = (
            service.backend(args.backend)
            if args.backend
            else service.least_busy(operational=True, simulator=False, min_num_qubits=args.n)
        )

    print(f"== Izbrani procesor: {backend.name} ({backend.num_qubits} kubitov) ==")

    qc = ghz_linearno(args.n)
    pm = generate_preset_pass_manager(backend=backend, optimization_level=1)
    isa = pm.run(qc)
    print(
        f"  pred prevajanjem: kubitov={qc.num_qubits} globina={qc.depth()} "
        f"2q-vrat={st_dvokubitnih(qc)}"
    )
    print(
        f"  po prevajanju:    globina={isa.depth()} 2q-vrat={st_dvokubitnih(isa)} "
        f"vrata={dict(isa.count_ops())}"
    )

    if not args.run:
        print("\nBrez --run: na procesor ni bilo nič poslano.")
        return

    from qiskit_ibm_runtime import SamplerV2 as Sampler

    t0 = time.time()
    job = Sampler(mode=backend).run([isa], shots=args.shots)
    job_id = job.job_id()
    print(f"\nNaloga poslana: job ID = {job_id} (čakam na rezultat ...)")
    rezultat = job.result()
    stetje = rezultat[0].data.meas.get_counts()
    trajanje = time.time() - t0

    nicle, enice = "0" * args.n, "1" * args.n
    p_ghz = (stetje.get(nicle, 0) + stetje.get(enice, 0)) / args.shots
    najpogostejsi = sorted(stetje.items(), key=lambda kv: -kv[1])[:6]
    print(f"  P({nicle}) + P({enice}) = {p_ghz:.3f}")
    print(f"  najpogostejši izidi: {najpogostejsi}")
    print(f"  čas od oddaje do rezultata: {trajanje:.1f} s")

    kvantni_cas = None
    try:
        kvantni_cas = job.usage()  # sekunde procesorskega časa
        print(f"  porabljen čas procesorja: {kvantni_cas} s")
    except Exception:  # noqa: BLE001
        pass

    REZULTATI.mkdir(exist_ok=True)
    zapis = {
        "cas": datetime.now(timezone.utc).isoformat(),
        "job_id": job_id,
        "backend": backend.name,
        "fake": args.fake,
        "vezje": qc.name,
        "shots": args.shots,
        "globina_isa": isa.depth(),
        "dvokubitna_isa": st_dvokubitnih(isa),
        "p_ghz": p_ghz,
        "porabljen_cas_s": kvantni_cas,
        "stetje": stetje,
    }
    with open(REZULTATI / "naloge.jsonl", "a") as f:
        f.write(json.dumps(zapis) + "\n")
    print(f"  zapisano v {REZULTATI / 'naloge.jsonl'}")


if __name__ == "__main__":
    main()
