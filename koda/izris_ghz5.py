"""Izriše porazdelitev izidov 5-kubitnega GHZ s prvega zagona na procesorju IBM.

Bere zadnji ne-fake zapis za vezje ghz_lin_5 iz rezultati/naloge.jsonl in shrani
sliko v predlogo zbornika (Skupina20/img/ghz5_ibm.pdf).

Zagon:  python koda/izris_ghz5.py
"""
import json
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt

KOREN = Path(__file__).resolve().parent.parent
VHOD = KOREN / "rezultati" / "naloge.jsonl"
IZHOD = KOREN / "Predloga kvantno procesiranje" / "Latex predloga kvantno procesiranje" / "Skupina20" / "img" / "ghz5_ibm.pdf"

MODRA = "#2a78d6"   # izida GHZ
SIVA = "#898781"    # ostali izidi
CRNILO = "#52514e"
MREZA = "#e1e0d9"
PRAG = 5            # izidi z manj zadetki gredo v "ostali"


def main():
    zapisi = [json.loads(v) for v in VHOD.read_text(encoding="utf-8").splitlines() if v.strip()]
    zapis = [z for z in zapisi if not z["fake"] and z["vezje"] == "ghz_lin_5"][-1]
    stetje, shots, n = zapis["stetje"], zapis["shots"], 5

    pogosti = sorted(((k, v) for k, v in stetje.items() if v >= PRAG), key=lambda kv: -kv[1])
    ostali = sum(v for v in stetje.values() if v < PRAG)
    oznake = [k for k, _ in pogosti] + [f"ostali ({sum(1 for v in stetje.values() if v < PRAG)})"]
    vrednosti = [v / shots for _, v in pogosti] + [ostali / shots]
    ghz = {"0" * n, "1" * n}
    barve = [MODRA if o in ghz else SIVA for o in oznake]

    plt.rcParams.update({"font.family": "serif", "font.size": 9})
    fig, ax = plt.subplots(figsize=(5.2, 2.4))
    ax.bar(range(len(oznake)), vrednosti, color=barve, width=0.7, edgecolor="white", linewidth=1)
    for i, v in enumerate(vrednosti[:2]):
        ax.text(i, v - 0.015, f"{v:.3f}".replace(".", ","), ha="center", va="top", color="white", fontsize=7.5, rotation=90)
    ax.axhline(0.5, color=CRNILO, linewidth=0.8, linestyle=(0, (3, 3)))
    ax.text(len(oznake) - 0.5, 0.505, "idealno: 0,5", ha="right", va="bottom", color=CRNILO, fontsize=8)
    ax.set_xticks(range(len(oznake)))
    ax.set_xticklabels(oznake, rotation=60, ha="right", family="monospace", fontsize=7.5)
    ax.set_ylabel("verjetnost")
    ax.set_ylim(0, 0.58)
    ax.yaxis.grid(True, color=MREZA, linewidth=0.6)
    ax.set_axisbelow(True)
    for s in ("top", "right"):
        ax.spines[s].set_visible(False)
    for s in ("left", "bottom"):
        ax.spines[s].set_color(SIVA)
    ax.tick_params(colors=CRNILO)
    ax.legend(handles=[plt.Rectangle((0, 0), 1, 1, color=MODRA), plt.Rectangle((0, 0), 1, 1, color=SIVA)],
              labels=["izida GHZ", "napačni izidi"], frameon=False, fontsize=8, loc="center right")
    fig.tight_layout()
    IZHOD.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(IZHOD)
    print(f"P(00000)+P(11111) = {sum(stetje.get(k, 0) for k in ghz) / shots:.3f}  ->  {IZHOD}")


if __name__ == "__main__":
    main()
