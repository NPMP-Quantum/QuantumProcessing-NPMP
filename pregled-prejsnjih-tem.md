# Pregled tem iz prejšnjih let (QC) in izbira nove teme

Viri: zborniki 2017/18–2023/24 (filebin) in 2025/26 (repozitorij).
**Zbornik 2024/25 manjka** – preverjanje za to leto ni bilo mogoče.

## Teme s področja kvantnega računanja, ki so že bile obdelane

| Leto | Poglavje | Kaj so dejansko naredili |
|---|---|---|
| 2019/20 | Implementing a quantum computer simulator in Python | lasten simulator |
| 2019/20 | Kvantne nevronske mreže – pregled področja | pregled |
| 2019/20 | Shorov algoritem | implementacija |
| 2019/20 | Kvantno procesiranje skozi linearno algebro | teorija |
| 2019/20 | Quantum teleportation and superdense coding | implementacija |
| 2020/21 | Simulacija kvantnega računalnika v jeziku C++ | lasten simulator |
| 2021/22 | Kvantna izmenjava enkripcijskega ključa | QKD (BB84) |
| 2021/22 | Simulacija in vizualizacija v kvantnem procesiranju | simulator/vizualizacija |
| 2021/22 | Simonov algoritem | implementacija |
| 2021/22 | Pregled tehnologij za implementacijo kvantnih računalnikov | pregled |
| 2022/23 | Primerjalniki v kvantnih vezjih | kvantni komparator |
| 2022/23 | HHL algorithm | implementacija |
| 2022/23 | Groverjev algoritem | implementacija |
| 2023/24 | Analiza in implementacija Shorovega algoritma | implementacija |
| 2023/24 | Algoritem za kvantno megljenje (Quantum blur) | implementacija |
| 2023/24 | Shorov algoritem: odkrivanje moči … pri faktorizaciji | implementacija |
| 2023/24 | Post-kvantna kriptografija | pregled |
| 2023/24 | Zaznavanje in odpravljanje napak pri kvantnem procesiranju | Shorova 9-kubitna koda, **samo simulacija z ročno vstavljeno napako** |
| 2025/26 | Optimizacija pretočnosti prometa (D-Wave) | QUBO, kvantno žarenje |
| 2025/26 | Shor v več simulatorjih / primerjava simulatorjev za Shorov alg. (×2) + Shor za faktorizacijo | implementacija, primerjava simulatorjev |
| 2025/26 | Analiza ter implementacija Groverjevega algoritma | implementacija |
| 2025/26 | Pregled uporabe kv. algoritmov v medicini, logistiki, financah | pregled (VQE/QAOA le omenjena) |
| 2025/26 | Predstavitev in primerjava tipov kvantnih računalnikov | pregled |
| 2025/26 | Quantum Walk Implementation in Qrisp | implementacija |
| 2025/26 | Analiza in implementacija Simonovega algoritma | implementacija |
| 2025/26 | Delne vsote in utežene delne vsote amplitud | implementacija |
| 2025/26 | Analiza in implementacija algoritma Bernstein-Vazirani | implementacija, zagon na IBM Fez |
| 2025/26 | Primerjava kvantnih pristopov za problem N-kraljic | implementacija |
| 2025/26 | Foundational Quantum Algorithms: Grover, Deutsch–Jozsa, Shor | implementacija |
| 2025/26 | Seštevanje v kvantnih računalnikih (QCADesigner-E) | seštevalnik |

Iskanje po celotnem besedilu vseh zbornikov: **GHZ, CHSH/Bellove neenakosti,
kvantni volumen, randomized benchmarking, ZNE, ublažitev napak (mitigation),
dinamično razklapljanje (dynamical decoupling), ponavljalna koda – 0 zadetkov.**
VQE in QAOA se pojavita samo kot omemba v preglednem poglavju.

## Ugotovitev

Skoraj vse dosedanje QC naloge so implementacija znanega algoritma (to po
letošnjih navodilih ne zadošča več). Nihče še ni sistematično **meril, kako šum
na realnem procesorju vpliva na rezultat**, kar letošnja navodila izrecno
zahtevajo (idealni simulator vs. šumni model vs. realni procesor).

## Neuporabljene teme (izvedljive v ~2 tednih)

1. **Meja prepletenosti na procesorju IBM (stanja GHZ)** – priporočeno.
   *Vprašanje:* Koliko kubitov lahko procesor IBM Heron prepleta v pravo
   večdelno prepleteno stanje GHZ (zvestoba F > 0,5) in koliko to mejo
   premakneta zasnova vezja (linearna veriga vs. drevo z logaritemsko globino)
   ter dinamično razklapljanje + ublažitev napak branja?
   *Metrike:* zvestoba F = (P + C)/2 iz populacij in paritetnih oscilacij,
   globina, št. dvokubitnih vrat. Poceni (malo procesorskega časa), jasna
   številčna meja, aktualno (IBM in Google objavljata GHZ z 50–120 kubiti).
2. **Ponavljalna koda na realnem procesorju** – ali logična napaka pada z
   razdaljo d = 3, 5, 7 in pri kateri d preseže nezaščiten kubit. Tematsko
   blizu 2023/24 (QEC), vendar tam le teorija + simulacija z vstavljeno napako.
3. **Primerjava tehnik ublažitve napak** (branje, ZNE, Paulijevo
   prepletanje/twirling) – katera da največji prirastek natančnosti na dodatni
   posnetek (shot).
4. **VQE za molekulo H₂** – kako blizu kemijske natančnosti (1,6 mHa) pride
   šumni procesor in koliko pomaga ublažitev napak.
