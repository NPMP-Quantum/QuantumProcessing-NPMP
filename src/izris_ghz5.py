"""Izriše porazdelitev izidov 5-kubitnega GHZ s procesorja IBM (zadnja nefake naloga z vezjem ghz_lin_5).

Bere rezultati/naloge.jsonl, sliko shrani v porocilo-seminarska-naloga/img/ghz5_ibm.pdf.
Zagon:  python src/izris_ghz5.py
"""
import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt

from ibm_skupno import SLIKE, beri_dnevnik

IZHOD = SLIKE / "ghz5_ibm.pdf"
VEZJE = "ghz_lin_5"
N = 5

MODRA = "#2a78d6"
SIVA = "#898781"
CRNILO = "#52514e"
MREZA = "#e1e0d9"
PRAG = 5  # izidi z manj zadetki gredo v "ostali"


def zadnje_stetje():
    stetja = [v["stetje"] for z in beri_dnevnik() if not z["fake"] for v in z["vezja"]
              if v["ime"] == VEZJE and v["stetje"]]
    if not stetja:
        raise SystemExit(f"V rezultati/naloge.jsonl ni izidov vezja {VEZJE} s procesorja.")
    return stetja[-1]


def main():
    stetje = zadnje_stetje()
    shots = sum(stetje.values())
    pogosti = sorted(((k, v) for k, v in stetje.items() if v >= PRAG), key=lambda kv: -kv[1])
    ostali = [v for v in stetje.values() if v < PRAG]
    oznake = [k for k, _ in pogosti] + [f"ostali ({len(ostali)})"]
    vrednosti = [v / shots for _, v in pogosti] + [sum(ostali) / shots]
    ghz = {"0" * N, "1" * N}
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
