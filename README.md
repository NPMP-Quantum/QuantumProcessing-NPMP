# Meja prepletenosti na procesorju IBM: stanja GHZ

Seminarska naloga pri predmetu NPMP 2026/27 (kvantno procesiranje), Skupina 20: Dominik Krašovec in Erik Radovičevič.

**Raziskovalno vprašanje.** Koliko kubitov lahko procesor IBM Heron (ibm_fez, 156 kubitov) pripravi v stanje GHZ z
zvestobo F > 0,5 (dokaz prave večdelne prepletenosti) in za koliko to mejo premakneta zasnova vezja (linearna veriga ali
drevo) ter dinamično razklapljanje (DD) in ublažitev napak branja?

Zvestobo merimo kot F = (P + C) / 2: P je delež izidov 0...0 in 1...1, C pa amplituda paritetnih oscilacij, ki jo iz
meritev pri 9 fazah dobimo z diskretno Fourierovo transformacijo. Podrobnosti so v poročilu
(`porocilo-seminarska-naloga/main.tex`, razdelek Metode).

## Vsebina

| Pot | Vsebina |
|---|---|
| `src/ghz.py` | izbira kubitov (veriga, drevo BFS), vezja GHZ in meritev koherence, prevajanje z razporejanjem ALAP in DD, idealni in šumni simulator, ublažitev branja, P, C, F z zankanjem |
| `src/napoved.py` | klasični model proračuna napak: napoved F iz kalibracije procesorja, brez simulacije |
| `src/poskus.py` | en simulacijski poskus za seznam N; zapiše `rezultati/sim/<ime>.json` |
| `src/ponovi_objave.py` | ponovitev prejšnjih rezultatov v šumni simulaciji (B0: naš 5-kubitni zagon z 2. 11. 2026) |
| `src/qpu.py` | poskus na procesorju IBM z nadzorom porabe: `nacrt`, `poslji`, `prevzemi`, `analiza` |
| `src/ibm_status.py` | pregled računa, porabe, procesorja in nalog (samo bere) |
| `src/preveri_branje.py` | preverba neodvisnosti napak branja na shranjenih kalibracijskih izidih (samo bere datoteke) |
| `src/izris_rezultatov.py` | graf $F(N)$, tabeli poročila in meje $N_{\max}$ iz shranjenih izidov (samo bere datoteke) |
| `src/ibm_poslji.py` | prejšnja skripta za oddajo posameznega vezja (za poskuse jo nadomešča `qpu.py`) |
| `src/izris_ghz5.py` | graf izidov 5-kubitnega preizkusa na ibm_fez z 2. 11. 2026 |
| `tests/` | samodejni testi: idealni simulator da F = 1, ublažitev branja, faze, proračun porabe |
| `rezultati/naloge.jsonl` | dnevnik vseh poslov na procesorju (job ID, postavitev kubitov, poraba) |
| `rezultati/sim/`, `rezultati/qpu/` | izidi simulacij in poslov: parametri, različice, števila izidov, rezultati |
| `porocilo-seminarska-naloga/` | poglavje za zbornik (`main.tex`, `references.bib`, `img/`) in prijava teme (`tasks/predlog_teme.tex`) |

## Namestitev

```bash
python3 -m venv .venv
.venv/bin/pip install -r requirements.txt
```

Uporabljene različice: Qiskit 2.6.1, Qiskit Aer 0.18.2, qiskit-ibm-runtime 0.51.0 (vse v `requirements.txt`).

## Ponovitev rezultatov

Vsi ukazi se poženejo iz korena repozitorija. Simulacije so lahko dolgotrajne; spremenljivka `GHZ_NITI` določi število niti
simulatorja Aer (npr. `GHZ_NITI=1`), privzeto jih Aer izbere sam.

1. Testi (idealni simulator, analiza, proračun porabe):
   ```bash
   .venv/bin/python -m pytest tests -q
   ```
2. Ponovitev 5-kubitnega zagona na šumnem simulatorju FakeFez in primerjalna tabela:
   ```bash
   .venv/bin/python src/ponovi_objave.py B0
   .venv/bin/python src/ponovi_objave.py --tabela
   ```
3. Napoved klasičnega modela za obe zasnovi:
   ```bash
   .venv/bin/python src/napoved.py --backend FakeFez --zasnove veriga drevo --n 10 16 22 28 34 40 50 64 76
   ```
4. Šumna simulacija verige (primer):
   ```bash
   .venv/bin/python src/poskus.py --backend FakeFez --zasnova veriga --n 5 10 13 --metoda pariteta --ime veriga_fakefez
   ```
5. Procesor IBM. **Porabi procesorski čas** (Open Plan: 600 s v 28 dneh), zato najprej `nacrt`, ki ne odda ničesar.
   Žeton in instanco vpišite v `.env` (predloga `.env.example`). Celotno pot lahko brez procesorja preizkusite z `--fake`.
   ```bash
   .venv/bin/python src/qpu.py nacrt --ime pilot --n-veriga 10 22 --n-drevo 20 40 --dd oboje --faze 9
   .venv/bin/python src/qpu.py poslji --ime pilot --n-veriga 10 22 --n-drevo 20 40 --dd oboje --faze 9 \
       --max-sekund <dogovorjena meja> --max-poslov 1
   .venv/bin/python src/qpu.py analiza --ime pilot
   ```
   `poslji` brez `--max-sekund` ne odda ničesar. Vsak posel dobi zgornjo mejo trajanja, ki se pred oddajo rezervira v tej
   meji; nov zagon se zavrne, dokler kateri od prejšnjih poslov ni obračunan. Če se čakanje prekine, izide prevzame
   `qpu.py prevzemi --ime <ime>`.

   Preostali posli iz poročila (izidi so v `rezultati/qpu/`, zato jih za analizo ni treba ponavljati):
   ```bash
   .venv/bin/python src/qpu.py poslji --ime glavni --n-veriga 16 28 34 --n-drevo 30 46 50 56 --dd oboje --faze 9 \
       --max-sekund <meja> --max-poslov 1 --faktor-omejitve 1.5 --model-posnetek-ms 0.284
   .venv/bin/python src/qpu.py poslji --ime zgostitev --n-veriga 19 25 --n-drevo 25 53 --dd oboje --faze 9 \
       --max-sekund <meja> --max-poslov 1 --faktor-omejitve 1.5 --model-posnetek-ms 0.284
   .venv/bin/python src/qpu.py poslji --ime dodatni --zasnove drevo --n-drevo 25 50 53 --brez-kubitov 113 131 --dd oboje --faze 9 \
       --max-sekund <meja> --max-poslov 1 --faktor-omejitve 1.5 --model-posnetek-ms 0.284
   ```
6. Slika, tabele in preverbe iz shranjenih izidov (brez procesorja):
   ```bash
   .venv/bin/python src/qpu.py analiza --ime glavni          # enako za pilot, zgostitev, dodatni
   .venv/bin/python src/izris_rezultatov.py                  # img/ghz_fn.pdf, tabeli poročila, meje N_max, učinek DD
   .venv/bin/python src/preveri_branje.py                    # neodvisnost napak branja, napaka branja po kubitih
   ```

Poročilo je poglavje zbornika: `porocilo-seminarska-naloga/main.tex` se prevede znotraj predloge zbornika kot mapa
`Skupina20`.
