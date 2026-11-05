"""Skupno za ibm_status.py, ibm_poslji.py in izris_ghz5.py: žeton, povezava, dnevnik nalog."""

import json
import os
import sys
from pathlib import Path

KOREN = Path(__file__).resolve().parent.parent
REZULTATI = KOREN / "rezultati"
DNEVNIK = REZULTATI / "naloge.jsonl"
SLIKE = KOREN / "porocilo-seminarska-naloga" / "img"


def nalozi_env():
    """Prebere .env v korenu repozitorija (če obstaja)."""
    pot = KOREN / ".env"
    if not pot.exists():
        return
    for vrstica in pot.read_text().splitlines():
        vrstica = vrstica.strip()
        if not vrstica or vrstica.startswith("#") or "=" not in vrstica:
            continue
        kljuc, vrednost = vrstica.split("=", 1)
        os.environ.setdefault(kljuc.strip(), vrednost.strip().strip('"').strip("'"))


def povezi():
    from qiskit_ibm_runtime import QiskitRuntimeService

    token = os.environ.get("QISKIT_IBM_TOKEN")
    instance = os.environ.get("QISKIT_IBM_INSTANCE") or None
    if token:
        return QiskitRuntimeService(channel="ibm_quantum_platform", token=token, instance=instance)
    try:
        return QiskitRuntimeService()
    except Exception as e:  # noqa: BLE001
        sys.exit(f"Ni žetona: nastavite QISKIT_IBM_TOKEN (okolje ali .env).\nPodrobnosti: {e}")


def st_dvokubitnih(qc):
    return sum(1 for inst in qc.data if inst.operation.num_qubits == 2)


def beri_dnevnik():
    """Zapisi iz naloge.jsonl; za vsak job ID velja zadnji zapis.

    Zapise iz prve različice (eno vezje: polji "vezje" in "stetje") pretvori v obliko z "vezja".
    """
    if not DNEVNIK.exists():
        return []
    zadnji = {}
    for vrstica in DNEVNIK.read_text(encoding="utf-8").splitlines():
        if not vrstica.strip():
            continue
        z = json.loads(vrstica)
        if "vezja" not in z:
            z["vezja"] = [{
                "ime": z.pop("vezje"),
                "globina_isa": z.pop("globina_isa", None),
                "dvokubitna_isa": z.pop("dvokubitna_isa", None),
                "stetje": z.pop("stetje", None),
            }]
        zadnji[z["job_id"]] = z
    return list(zadnji.values())


def dodaj_v_dnevnik(zapis):
    REZULTATI.mkdir(exist_ok=True)
    with open(DNEVNIK, "a", encoding="utf-8") as f:
        f.write(json.dumps(zapis) + "\n")


def stetja_iz_rezultata(rezultat):
    """Izidi (slovar bitni niz -> število) za vsako vezje v rezultatu SamplerV2."""
    return [pub.join_data().get_counts() for pub in rezultat]


def dopolni_zapis(job_id, rezultat, poraba_s):
    """Ko so izidi znani, v dnevnik doda dopolnjen zapis naloge. Vrne zapis ali None, če naloge ni v dnevniku."""
    zapis = next((z for z in beri_dnevnik() if z["job_id"] == job_id), None)
    if zapis is None:
        return None
    stetja = stetja_iz_rezultata(rezultat)
    if len(stetja) != len(zapis["vezja"]):
        raise ValueError(f"rezultat ima {len(stetja)} vezij, dnevnik {len(zapis['vezja'])}")
    for vezje, stetje in zip(zapis["vezja"], stetja):
        vezje["stetje"] = stetje
    if poraba_s:
        zapis["porabljen_cas_s"] = poraba_s
    dodaj_v_dnevnik(zapis)
    return zapis
