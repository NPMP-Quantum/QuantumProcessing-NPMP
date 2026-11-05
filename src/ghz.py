"""Stanja GHZ na procesorjih IBM: vezja, merjenje zvestobe, ublažitev napak branja.

Zvestoba F = (P + C) / 2 (Sackett 2000, Wei 2020, Mooney 2021):
  P  populacija: p(0...0) + p(1...1),
  C  koherenca: 2 |rho_{0...0, 1...1}|, izmerjena na dva načina:
     - paritetne oscilacije: vsak kubit merimo v bazi cos(phi) X + sin(phi) Y, pariteta = C cos(N phi + phi0),
     - MQC (multiple quantum coherences): priprava, Rz(phi) na vseh, X na vseh (refokusiranje), obratna priprava,
       S(phi) = p(0...0), idealno (1 + cos(N phi)) / 2; C = 2 sqrt(I_N), I_N je velikost komponente s frekvenco N.
Faze: phi_j = pi j / (N + 1), j = 0 ... 2N + 1 (Wei 2020); diskretna Fourierova transformacija tedaj točno loči
vse frekvence -N ... N.

Ublažitev napak branja je lokalna (ena matrika 2x2 na kubit, kot Mooney 2021). Vse naše količine so linearne v
porazdelitvi izidov, zato jih popravimo z utežmi na izid in ne potrebujemo matrike velikosti 2^N.
"""

from __future__ import annotations

import math
import os
from collections import deque
from dataclasses import dataclass

import numpy as np
from qiskit import QuantumCircuit
from qiskit.circuit.library import XGate
from qiskit.transpiler import PassManager, generate_preset_pass_manager
from qiskit.transpiler.passes import ALAPScheduleAnalysis, PadDynamicalDecoupling

# število niti simulatorja (0 = vse jedra); GHZ_NITI omeji porabo procesorja in pomnilnika
NITI = int(os.environ.get("GHZ_NITI") or 0)

# ---------------------------------------------------------------------------------------------- čip


def dvokubitna_vrata(backend):
    for ime in ("cz", "ecr", "cx"):
        if ime in backend.target.operation_names:
            return ime
    raise ValueError("procesor nima znanih dvokubitnih vrat")


# Kubiti, ki jih izbira ne sme uporabiti: napaka, izmerjena v prejšnjem poslu, ki je objavljena kalibracija še ne kaže.
IZKLJUCENI_KUBITI = set()


def napake(backend):
    """Napake branja po kubitih in napake dvokubitnih vrat po povezavah (iz kalibracije lažnega/pravega procesorja)."""
    t = backend.target
    branje = {}
    for q, lastnosti in t["measure"].items():
        branje[q[0]] = (lastnosti.error if lastnosti and lastnosti.error is not None else 0.05)
    vrata = {}
    for q, lastnosti in t[dvokubitna_vrata(backend)].items():
        e = lastnosti.error if lastnosti and lastnosti.error is not None else 0.05
        kljuc = tuple(sorted(q))
        vrata[kljuc] = min(e, vrata.get(kljuc, 1.0))
    sosedi = {q: set() for q in range(backend.num_qubits)}
    for a, b in vrata:
        sosedi[a].add(b)
        sosedi[b].add(a)
    # kubiti z napako 1 (pokvarjeni) ali napako branja >= 0,5 ne pridejo v poštev
    slabi = {q for q, e in branje.items() if e >= 0.5} | IZKLJUCENI_KUBITI
    for (a, b), e in vrata.items():
        if e >= 1.0:
            sosedi[a].discard(b)
            sosedi[b].discard(a)
    return branje, vrata, sosedi, slabi


def cena(kubiti, povezave, branje, vrata):
    return sum(branje[q] for q in kubiti) + sum(vrata[tuple(sorted(p))] for p in povezave)


def najdi_pot(backend, n, proracun=20000):
    """Linearna veriga n kubitov po grafu povezav: najcenejša najdena enostavna pot (iskanje v globino z vračanjem)."""
    branje, vrata, sosedi, slabi = napake(backend)
    najboljsa, najboljsa_cena = None, math.inf
    zacetki = sorted((q for q in sosedi if q not in slabi), key=lambda q: branje[q])
    for zacetek in zacetki:
        koraki = [0]

        def dfs(pot, obiskani):
            koraki[0] += 1
            if len(pot) == n:
                return list(pot)
            if koraki[0] > proracun:
                return None
            zadnji = pot[-1]
            kandidati = sorted((q for q in sosedi[zadnji] if q not in obiskani and q not in slabi),
                               key=lambda q: vrata[tuple(sorted((zadnji, q)))] + branje[q])
            for q in kandidati:
                pot.append(q)
                obiskani.add(q)
                r = dfs(pot, obiskani)
                if r:
                    return r
                pot.pop()
                obiskani.discard(q)
            return None

        pot = dfs([zacetek], {zacetek})
        if pot:
            c = cena(pot, zip(pot, pot[1:]), branje, vrata)
            if c < najboljsa_cena:
                najboljsa, najboljsa_cena = pot, c
    if najboljsa is None:
        raise ValueError(f"na čipu ni enostavne poti z {n} kubiti")
    return najboljsa


def nakljucna_pot(backend, n, rng, poskusi=1000):
    """Naključna enostavna pot n kubitov (naključen sprehod brez ponavljanja, z novim začetkom ob zastoju)."""
    _, _, sosedi, slabi = napake(backend)
    dobri = [q for q in sosedi if q not in slabi]
    for _ in range(poskusi):
        pot = [int(rng.choice(dobri))]
        while len(pot) < n:
            kandidati = [q for q in sosedi[pot[-1]] if q not in pot and q not in slabi]
            if not kandidati:
                break
            pot.append(int(rng.choice(kandidati)))
        if len(pot) == n:
            return pot
    raise ValueError(f"ni naključne poti z {n} kubiti")


CENA_NIVOJA = 0.0015


def najdi_drevo(backend, n):
    """Drevo n kubitov z iskanjem v širino (BFS) iz korena z najmanjšo oceno napake (napake kubitov in vrat
    ter cena globine, CENA_NIVOJA na kubit in nivo).

    Vrne (kubiti v vrstnem redu BFS, starsi), kjer je starsi[i] indeks starša kubita i (koren ima None)."""
    branje, vrata, sosedi, slabi = napake(backend)
    najboljse, najboljsi_kljuc = None, None
    for koren in sosedi:
        if koren in slabi:
            continue
        vrstni_red, starsi, nivo = [koren], {koren: None}, {koren: 0}
        vrsta = deque([koren])
        while vrsta and len(vrstni_red) < n:
            q = vrsta.popleft()
            for s in sorted(sosedi[q], key=lambda s: vrata[tuple(sorted((q, s)))] + branje[s]):
                if s in starsi or s in slabi or len(vrstni_red) >= n:
                    continue
                starsi[s], nivo[s] = q, nivo[q] + 1
                vrstni_red.append(s)
                vrsta.append(s)
        if len(vrstni_red) < n:
            continue
        povezave = [(q, starsi[q]) for q in vrstni_red[1:]]
        # napake kubitov in vrat + cena globine: vsak nivo drevesa pomeni ~2 plasti vrat (~0,15 us) čakanja za
        # ~n kubitov, pri T2 ~ 100 us je to ~0,0015 izgube koherence na kubit in nivo
        globina_drevesa = max(nivo[q] for q in vrstni_red)
        kljuc = cena(vrstni_red, povezave, branje, vrata) + CENA_NIVOJA * n * globina_drevesa
        if najboljsi_kljuc is None or kljuc < najboljsi_kljuc:
            indeks = {q: i for i, q in enumerate(vrstni_red)}
            najboljse = (vrstni_red, [None] + [indeks[starsi[q]] for q in vrstni_red[1:]])
            najboljsi_kljuc = kljuc
    if najboljse is None:
        raise ValueError(f"na čipu ni drevesa z {n} kubiti")
    return najboljse


# ------------------------------------------------------------------------------------------- vezja


@dataclass
class Zasnova:
    """Logično vezje priprave GHZ in kubiti na čipu, na katere ga postavimo (kubit i -> postavitev[i])."""
    ime: str
    priprava: QuantumCircuit
    postavitev: list


def ghz_veriga(postavitev):
    n = len(postavitev)
    qc = QuantumCircuit(n, name=f"veriga_{n}")
    qc.h(0)
    for i in range(n - 1):
        qc.cx(i, i + 1)
    return Zasnova("veriga", qc, list(postavitev))


def ghz_drevo(postavitev, starsi):
    n = len(postavitev)
    qc = QuantumCircuit(n, name=f"drevo_{n}")
    qc.h(0)
    for i in range(1, n):
        qc.cx(starsi[i], i)
    return Zasnova("drevo", qc, list(postavitev))


def zasnova_za(backend, ime, n):
    if ime == "veriga":
        return ghz_veriga(najdi_pot(backend, n))
    if ime == "drevo":
        return ghz_drevo(*najdi_drevo(backend, n))
    raise ValueError(ime)


def faze(n, stevilo=None):
    """Faze za meritev koherence.

    Brez `stevilo`: phi_j = pi j / (n + 1), j = 0 ... 2n + 1 (Wei 2020): točno za obe metodi (MQC ima vse frekvence -n ... n).
    S `stevilo` = M: phi_k = pi k / M, k = 0 ... M - 1 (pol kroga), samo za paritetne oscilacije. Pariteta ima le
    frekvence n, n - 2, ..., -n; vsota po teh fazah izloči frekvenco n - 2m za vsak m, ki ni večkratnik M, zato je
    rezultat točen pri M > n, pri M <= n pa ostane le prispevek koherenc z m = M, 2M, ... hkratnimi preklopi
    (zanemarljivo). Pogoj: n ni večkratnik M (sicer se prišteje konjugirani del signala)."""
    if stevilo is None:
        return [math.pi * j / (n + 1) for j in range(2 * n + 2)]
    if stevilo <= n and n % stevilo == 0:
        raise ValueError(f"n = {n} je večkratnik števila faz {stevilo}: izberi drugo število faz")
    return [math.pi * k / stevilo for k in range(stevilo)]


def vezje_populacija(priprava):
    qc = priprava.copy(name=f"{priprava.name}_P")
    qc.measure_all()
    return qc


def vezje_pariteta(priprava, phi):
    """Meritev vsakega kubita v bazi cos(phi) X + sin(phi) Y: Rz(-phi), nato H, nato meritev v bazi Z."""
    n = priprava.num_qubits
    qc = priprava.copy(name=f"{priprava.name}_par_{phi:.4f}")
    qc.barrier()
    qc.rz(-phi, range(n))
    qc.h(range(n))
    qc.measure_all()
    return qc


def vezje_mqc(priprava, phi):
    """MQC z refokusirnim pulzom X (Wei 2020, Mooney 2021). Pregrade preprečijo, da bi prevajalnik pripravo in
    obratno pripravo pokrajšal."""
    n = priprava.num_qubits
    qc = priprava.copy(name=f"{priprava.name}_mqc_{phi:.4f}")
    qc.barrier()
    qc.rz(phi, range(n))
    qc.x(range(n))
    qc.barrier()
    qc.compose(priprava.inverse(), inplace=True)
    qc.measure_all()
    return qc


def vezja_kalibracije(n):
    """Dve vezji za lokalno ublažitev branja: vsi kubiti v |0> in vsi v |1>."""
    nic = QuantumCircuit(n, name="kal_0")
    nic.measure_all()
    ena = QuantumCircuit(n, name="kal_1")
    ena.x(range(n))
    ena.measure_all()
    return [nic, ena]


def vezja_poskusa(zasnova, metoda, faze_seznam):
    """Vsa vezja enega poskusa: kalibracija (2), populacija (1, samo pri metodi pariteta) in faze."""
    p = zasnova.priprava
    vezja = vezja_kalibracije(p.num_qubits)
    if metoda == "pariteta":
        vezja.append(vezje_populacija(p))
        vezja += [vezje_pariteta(p, f) for f in faze_seznam]
    elif metoda == "mqc":
        if len(faze_seznam) != 2 * p.num_qubits + 2:
            raise ValueError("MQC potrebuje vseh 2N + 2 faz (ima vse frekvence)")
        vezja.append(vezje_populacija(p))
        vezja += [vezje_mqc(p, f) for f in faze_seznam]
    else:
        raise ValueError(metoda)
    return vezja


# ------------------------------------------------------------------------------ prevajanje in zagon


def prevedi(vezja, backend, postavitev, dd=False, seed=7):
    """Prevajanje s fiksno postavitvijo kubitov in časovnim razporedom ALAP (da so čakanja vidna kot `delay`).

    dd=True vstavi zaporedje X-X v vsako dovolj dolgo čakanje (dinamično razklapljanje)."""
    pm = generate_preset_pass_manager(optimization_level=1, backend=backend, initial_layout=postavitev,
                                      seed_transpiler=seed, scheduling_method="alap")
    if dd:
        if backend.target.pulse_alignment != 1 or backend.target.acquire_alignment != 1:
            raise ValueError("DD v vezju predvideva poravnavo 1 dt (Heron); za ta procesor je treba dodati poravnavo")
        pm.scheduling = PassManager([
            ALAPScheduleAnalysis(target=backend.target),
            PadDynamicalDecoupling(target=backend.target, dd_sequence=[XGate(), XGate()]),
        ])
    return [_brez_praznih_kubitov(qc) for qc in pm.run(vezja)]


def _brez_praznih_kubitov(qc):
    """Razpored doda `delay` tudi na neuporabljene kubite čipa; odstranimo jih, da jih simulator lahko izpusti
    (na rezultat ne vplivajo, ker ti kubiti niso prepleteni z našimi)."""
    uporabljeni = {q for inst in qc.data if inst.operation.name not in ("barrier", "delay") for q in inst.qubits}
    novo = qc.copy_empty_like()
    for inst in qc.data:
        if inst.operation.name == "delay" and not set(inst.qubits) & uporabljeni:
            continue
        if inst.operation.name == "barrier":
            qubiti = [q for q in inst.qubits if q in uporabljeni]
            if qubiti:
                novo.barrier(qubiti)
            continue
        novo.append(inst)
    return novo


def lastnosti(qc, target=None):
    """Število uporabljenih kubitov, globina, dvokubitna vrata in ocenjeno trajanje [us] (če je podan target)."""
    uporabljeni = {qc.find_bit(q).index for inst in qc.data for q in inst.qubits
                   if inst.operation.name not in ("barrier", "delay")}
    dvo = sum(1 for inst in qc.data if inst.operation.num_qubits == 2 and inst.operation.name != "barrier")
    globina = qc.depth(lambda inst: inst.operation.name not in ("barrier", "delay"))
    trajanje = None
    if target is not None:
        try:
            trajanje = float(qc.estimate_duration(target, unit="u"))
        except Exception:  # noqa: BLE001  (logično vezje brez časov vrat)
            trajanje = None
    return {"kubiti": len(uporabljeni), "globina": globina, "dvokubitna": dvo, "trajanje_us": trajanje}


class SumniSimulator:
    """Aer s šumnim modelom procesorja, napake branja pa dodamo klasično po meritvi.

    Razlog: Aer 0.18 z metodo MPS obvisi, ko ima vezje hkrati termično relaksacijo in napako branja
    (opaženo na FakeMontrealV2). Napaka branja je klasična (preklop prebranega bita), zato jo uporabimo
    po simulaciji z istimi verjetnostmi, kot so v šumnem modelu (p(prebrano | stanje) za vsak kubit)."""

    def __init__(self, backend, metoda="matrix_product_state", seed=11):
        from qiskit_aer import AerSimulator
        from qiskit_aer.noise import NoiseModel

        self.branje = {}
        for napaka in NoiseModel.from_backend(backend).to_dict()["errors"]:
            if napaka["type"] == "roerror":
                for qubiti in napaka["gate_qubits"]:
                    self.branje[qubiti[0]] = np.array(napaka["probabilities"], dtype=float)
        # Aer iz `target` naredi simetrično napako (povprečje obeh smeri); kalibracija procesorja pa ima obe
        # smeri ločeno (|1> se bere slabše, ker med branjem razpade). Če jih imamo, uporabimo te.
        lastnosti_ = backend.properties() if hasattr(backend, "properties") else None
        if lastnosti_ is not None:
            for q in range(backend.num_qubits):
                try:
                    p10 = lastnosti_.qubit_property(q, "prob_meas1_prep0")[0]
                    p01 = lastnosti_.qubit_property(q, "prob_meas0_prep1")[0]
                except Exception:  # noqa: BLE001  (kubit brez podatka: ostane simetrična napaka)
                    continue
                self.branje[q] = np.array([[1 - p10, p10], [p01, 1 - p01]], dtype=float)
        self.branje_vir = "properties" if lastnosti_ is not None else "šumni model (simetrično)"
        self.seed = seed
        self.klic = 0
        brez_branja = NoiseModel.from_backend(backend, readout_error=False)
        _pauli_priblizek_dvokubitnih(brez_branja, dvokubitna_vrata(backend))
        self.sim = AerSimulator(method=metoda, noise_model=brez_branja, seed_simulator=seed,
                                  max_parallel_threads=NITI)
        self.rng = np.random.default_rng(seed)

    def pozeni(self, prevedena, shots):
        self.klic += 1
        rezultat = self.sim.run(prevedena, shots=shots, memory=True,
                                seed_simulator=self.seed + 1000 * self.klic).result()
        stetja = []
        for i, qc in enumerate(prevedena):
            klasicni_v_kubit = {qc.find_bit(inst.clbits[0]).index: qc.find_bit(inst.qubits[0]).index
                                for inst in qc.data if inst.operation.name == "measure"}
            nizi = rezultat.get_memory(i)
            st_bitov = len(nizi[0])
            biti = np.array([[c == "1" for c in reversed(s)] for s in nizi], dtype=bool)
            for k in range(st_bitov):
                p = self.branje.get(klasicni_v_kubit.get(k))
                if p is None:
                    continue
                r = self.rng.random(len(nizi))
                # p[t][m] = verjetnost, da stanje t preberemo kot m
                biti[:, k] = np.where(biti[:, k], r >= p[1][0], r < p[0][1])
            stetje = {}
            for vrstica in biti:
                niz = "".join("1" if b else "0" for b in reversed(vrstica))
                stetje[niz] = stetje.get(niz, 0) + 1
            stetja.append(stetje)
        return stetja


def _pauli_priblizek_dvokubitnih(sumni_model, ime_vrat):
    """Napako dvokubitnih vrat (depolarizacija + termična relaksacija, Krausov kanal) nadomesti s Paulijevim
    približkom (Pauli twirling): p_P = sum_k |tr(P K_k)|^2 / 16.

    Razlog: Aer 0.18 z metodo MPS ob dvokubitnem Krausovem kanalu FakeMontrealV2 obvisi. Približek ohrani
    povprečno zvestobo kanala in izgubi le nesimetrični del relaksacije med samimi vrati (trajanje ~0,3-0,5 us
    proti T1 ~ 100 us). Relaksacija med čakanji in na enokubitnih vratih ostane točna.
    Uporablja notranji slovar `_local_quantum_errors` (Aer 0.18.2, različica je zaklenjena v requirements.txt)."""
    from qiskit.quantum_info import Kraus, Pauli
    from qiskit_aer.noise import pauli_error

    oznake = [a + b for a in "IXYZ" for b in "IXYZ"]
    matrike = [Pauli(o).to_matrix() for o in oznake]
    napake_vrat = sumni_model._local_quantum_errors.get(ime_vrat, {})
    if not napake_vrat:
        raise RuntimeError(f"šumni model nima napak za vrata {ime_vrat}: Paulijevega približka ni mogoče narediti")
    for qubiti, napaka in list(napake_vrat.items()):
        krausi = Kraus(napaka).data
        p = np.array([sum(abs(np.trace(m.conj().T @ k)) ** 2 for k in krausi) / 16 for m in matrike])
        p = np.clip(p.real, 0, None)
        p /= p.sum()
        sumni_model._local_quantum_errors[ime_vrat][qubiti] = pauli_error(
            [(o, float(v)) for o, v in zip(oznake, p) if v > 1e-12])


class IdealniSimulator:
    def __init__(self, metoda="matrix_product_state", seed=11):
        from qiskit_aer import AerSimulator

        self.sim = AerSimulator(method=metoda, seed_simulator=seed, max_parallel_threads=NITI)
        self.seed, self.klic = seed, 0

    def pozeni(self, prevedena, shots):
        self.klic += 1
        rezultat = self.sim.run(prevedena, shots=shots, seed_simulator=self.seed + 1000 * self.klic).result()
        return [rezultat.get_counts(i) for i in range(len(prevedena))]


def simulator(backend=None, metoda="matrix_product_state", seed=11):
    return IdealniSimulator(metoda, seed) if backend is None else SumniSimulator(backend, metoda, seed)


def pozeni(prevedena, sim, shots):
    return sim.pozeni(prevedena, shots)


# --------------------------------------------------------------------------------------- analiza


def napake_branja(stetje_0, stetje_1):
    """Iz kalibracijskih vezij: e0[i] = p(prebrano 1 | stanje 0), e1[i] = p(prebrano 0 | stanje 1) za kubit i."""
    def delez_enk(stetje):
        biti, utezi = _v_matriko(stetje)
        return (biti * utezi[:, None]).sum(axis=0) / utezi.sum()

    return delez_enk(stetje_0), 1.0 - delez_enk(stetje_1)


def _v_matriko(stetje):
    """Izidi kot matrika bitov (vrstica = izid, stolpec i = kubit i) in vektor števil.

    Qiskit izpiše niz z zadnjim kubitom na levi, zato niz obrnemo."""
    nizi = list(stetje)
    biti = np.array([[c == "1" for c in reversed(s.replace(" ", ""))] for s in nizi], dtype=np.int8)
    return biti, np.array([stetje[s] for s in nizi], dtype=float)


def utezi(biti, kolicina, e0=None, e1=None):
    """Utež vsakega izida za izbrano količino; z e0, e1 vključuje lokalno ublažitev branja.

    kolicina: "vse0" (p(0...0)), "vse1" (p(1...1)), "pariteta" (<Z...Z>).
    Inverz lokalne matrike A = [[1-e0, e1], [e0, 1-e1]] (vrstica = prebrano, stolpec = pravo stanje)."""
    n = biti.shape[1]
    if e0 is None:
        e0, e1 = np.zeros(n), np.zeros(n)
    det = 1.0 - e0 - e1
    # inv[t, m] za t, m v {0, 1}, po kubitih
    inv00, inv01 = (1 - e1) / det, -e1 / det
    inv10, inv11 = -e0 / det, (1 - e0) / det
    m = biti.astype(bool)
    if kolicina == "vse0":
        faktorji = np.where(m, inv01, inv00)
    elif kolicina == "vse1":
        faktorji = np.where(m, inv11, inv10)
    elif kolicina == "pariteta":
        faktorji = np.where(m, inv01 - inv11, inv00 - inv10)
    else:
        raise ValueError(kolicina)
    return np.prod(faktorji, axis=1)


def koherenca(faze_seznam, vrednosti, n, metoda, polne_faze=True):
    """C iz izmerjenih vrednosti pri fazah: komponenta s frekvenco n (diskretna Fourierova transformacija).

    pariteta: vrednosti = <Pi(phi)>, C = 2 |c_n|;  mqc: vrednosti = S(phi), C = 2 sqrt(|c_n|).
    `polne_faze` je ostal zaradi združljivosti; način določa seznam faz (glej faze())."""
    phi = np.asarray(faze_seznam)
    v = np.asarray(vrednosti)
    c_n = np.mean(v * np.exp(-1j * n * phi))
    return 2 * abs(c_n) if metoda == "pariteta" else 2 * math.sqrt(abs(c_n))


def zvestoba(stetja, n, metoda, faze_seznam, ublazitev=True, polne_faze=True, zankanje=200, seed=0):
    """F, P, C in njihove negotovosti (zankanje po posnetkih) iz števil izidov enega poskusa.

    stetja: [kal_0, kal_1, populacija, faza_0, faza_1, ...] v vrstnem redu iz vezja_poskusa."""
    rng = np.random.default_rng(seed)
    kal0, kal1, pop, *fazna = stetja
    kolicina_faze = "pariteta" if metoda == "pariteta" else "vse0"
    biti_k0, st_k0 = _v_matriko(kal0)
    biti_k1, st_k1 = _v_matriko(kal1)
    biti_p, st_p = _v_matriko(pop)
    fazni = [_v_matriko(s) for s in fazna]

    def napake_iz(sk0, sk1):
        # e0 = delež prebranih 1 pri stanju 0, e1 = delež prebranih 0 pri stanju 1 (po kubitih)
        return (biti_k0 * sk0[:, None]).sum(0) / sk0.sum(), 1.0 - (biti_k1 * sk1[:, None]).sum(0) / sk1.sum()

    def izracun(sk0, sk1, sp, sf):
        e0, e1 = napake_iz(sk0, sk1) if ublazitev else (None, None)
        w_p = utezi(biti_p, "vse0", e0, e1) + utezi(biti_p, "vse1", e0, e1)
        P = float(np.dot(w_p, sp) / sp.sum())
        vrednosti = [np.dot(utezi(b, kolicina_faze, e0, e1), st) / st.sum() for (b, _), st in zip(fazni, sf)]
        C = koherenca(faze_seznam, vrednosti, n, metoda, polne_faze)
        return P, C, (P + C) / 2

    def vzorec(st):
        return rng.multinomial(int(st.sum()), st / st.sum()).astype(float)

    P, C, F = izracun(st_k0, st_k1, st_p, [st for _, st in fazni])
    # zankanje: na novo vzorčimo vse, tudi kalibracijo (negotovost popravka branja je del negotovosti F)
    vzorci = [izracun(vzorec(st_k0), vzorec(st_k1), vzorec(st_p), [vzorec(st) for _, st in fazni])
              for _ in range(zankanje)]
    sig = np.std(np.array(vzorci), axis=0, ddof=1) if zankanje > 1 else np.zeros(3)
    e0, e1 = napake_iz(st_k0, st_k1)
    return {"P": P, "C": C, "F": F, "sigma_P": float(sig[0]), "sigma_C": float(sig[1]), "sigma_F": float(sig[2]),
            "napaka_branja_povprecje": float(np.mean((e0 + e1) / 2))}
