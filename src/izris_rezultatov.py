"""Graf F(N), tabeli za poročilo in številke za besedilo iz shranjenih rezultatov na procesorju (samo bere datoteke).

Uporaba: python src/izris_rezultatov.py
Slika gre v porocilo-seminarska-naloga/img/ghz_fn.pdf, tabeli in povzetek na standardni izhod.
"""
import json
import math
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib.ticker import FuncFormatter

KOREN = Path(__file__).resolve().parent.parent
IZHOD = KOREN / "rezultati" / "qpu"
SLIKA = KOREN / "porocilo-seminarska-naloga" / "img" / "ghz_fn.pdf"
POSKUSI = ["pilot", "glavni", "zgostitev", "dodatni"]
BARVA_SUROVO = "#2a6fbb"
BARVA_UBLAZENO = "#c2571a"
SIVA = "#6b6b6b"
PRAG = 0.5


def preberi():
    """Točke vseh poslov; oznaka 'a' = postavitev s kubitom 113 po poslabšanju branja, 'b' = postavitev brez kubitov 113 in 131."""
    tocke = []
    for ime in POSKUSI:
        surovi = json.loads((IZHOD / f"{ime}.json").read_text())
        lastnosti = {(p["zasnova"], p["n"], p["dd"]): p["lastnosti_pred"] for z in surovi["posli"] for p in z["poskusi"]}
        for t in json.loads((IZHOD / f"{ime}_analiza.json").read_text())["rezultati"]:
            t["posel"] = ime
            t["pred"] = lastnosti[(t["zasnova"], t["n"], t["dd"])]
            t["oznaka"] = ""
            if t["zasnova"] == "drevo" and ime == "zgostitev":
                t["oznaka"] = "a"
            if t["zasnova"] == "drevo" and ime == "dodatni":
                t["oznaka"] = "b"
            tocke.append(t)
    return tocke


def spodnja(t, vrsta):
    return t[vrsta]["F"] - 2 * t[vrsta]["sigma_F"]


def intervali(tocke):
    """N_max po pravilu F - 2 sigma > 0,5, brez postavitev 'a'."""
    izpis = []
    for zasnova in ("veriga", "drevo"):
        for vrsta in ("surovo", "ublazeno"):
            for dd in (False, True):
                izbrane = [t for t in tocke if t["zasnova"] == zasnova and bool(t["dd"]) == dd and t["oznaka"] != "a"]
                dobri = [t["n"] for t in izbrane if spodnja(t, vrsta) > PRAG]
                n_max = max(dobri)
                naslednji = min(t["n"] for t in izbrane if t["n"] > n_max)
                izjeme = sorted(t["n"] for t in izbrane if spodnja(t, vrsta) <= PRAG and t["n"] <= n_max)
                izpis.append(f"{zasnova} {vrsta} DD={'da' if dd else 'ne'}: {n_max}-{naslednji}, izjeme pod mejo {izjeme}")
    return izpis


def vejica(x, _=None):
    return f"{x:g}".replace(".", ",")


def narisi(tocke):
    plt.rcParams.update({"font.family": "serif", "font.size": 8, "axes.spines.top": False, "axes.spines.right": False})
    fig, osi = plt.subplots(1, 2, figsize=(6.4, 3.0), sharey=True)
    for os_, zasnova, naslov in zip(osi, ("veriga", "drevo"), ("linearna veriga", "drevo BFS")):
        vse = [t for t in tocke if t["zasnova"] == zasnova]
        for vrsta, barva, oblika, kljuc_modela in (("surovo", BARVA_SUROVO, "o", "F_sur"), ("ublazeno", BARVA_UBLAZENO, "s", "F_ubl")):
            model = sorted({(t["n"], t["napoved"][kljuc_modela]) for t in vse if not t["dd"] and t["oznaka"] != "b"})
            os_.plot(*zip(*model), color=barva, lw=0.9, alpha=0.55, zorder=1)
            for dd in (False, True):
                izbrane = [t for t in vse if bool(t["dd"]) == dd and t["oznaka"] != "a"]
                os_.errorbar([t["n"] + (0.45 if dd else -0.45) for t in izbrane], [t[vrsta]["F"] for t in izbrane],
                             yerr=[2 * t[vrsta]["sigma_F"] for t in izbrane], fmt=oblika, ms=4, lw=0.8, color=barva,
                             mfc="white" if dd else barva, mew=0.9, zorder=3)
            slabe = [t for t in vse if t["oznaka"] == "a"]
            if slabe:
                os_.plot([t["n"] for t in slabe], [t[vrsta]["F"] for t in slabe], "x", color=SIVA, ms=4.5, mew=0.9, zorder=2)
        os_.axhline(PRAG, color=SIVA, lw=0.8, ls="--", zorder=0)
        os_.set_title(naslov, fontsize=8.5)
        os_.set_xlabel("število kubitov $N$")
        os_.set_ylim(0, 1.08)
        os_.yaxis.set_major_formatter(FuncFormatter(vejica))
        os_.grid(axis="y", color="#e4e4e4", lw=0.5)
        os_.set_axisbelow(True)
    osi[0].set_ylabel("zvestoba $F$")
    osi[0].text(1.0, PRAG + 0.012, "$F=0{,}5$", color=SIVA, fontsize=7, ha="right", va="bottom", transform=osi[0].get_yaxis_transform())
    roc = [plt.Line2D([], [], marker="o", color=BARVA_SUROVO, lw=0, ms=4, label="surovo, brez DD"),
           plt.Line2D([], [], marker="o", color=BARVA_SUROVO, mfc="white", lw=0, ms=4, label="surovo, z DD"),
           plt.Line2D([], [], color=BARVA_SUROVO, lw=0.9, alpha=0.55, label="model, surovo"),
           plt.Line2D([], [], marker="s", color=BARVA_UBLAZENO, lw=0, ms=4, label="ublaženo, brez DD"),
           plt.Line2D([], [], marker="s", color=BARVA_UBLAZENO, mfc="white", lw=0, ms=4, label="ublaženo, z DD"),
           plt.Line2D([], [], color=BARVA_UBLAZENO, lw=0.9, alpha=0.55, label="model, ublaženo"),
           plt.Line2D([], [], marker="x", color=SIVA, lw=0, ms=4.5, label="kubit 113 s slabim branjem")]
    fig.legend(handles=roc, loc="upper center", ncol=4, frameon=False, fontsize=7, handletextpad=0.4, columnspacing=1.1)
    fig.tight_layout(rect=(0, 0, 1, 0.88))
    SLIKA.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(SLIKA)
    plt.close(fig)


def f_zapis(d):
    return f"{d['F']:.3f}({round(d['sigma_F'] * 1000)})".replace(".", ",")


def stevilo(x, mest=3):
    return f"{x:.{mest}f}".replace(".", ",")


def ime_tocke(t):
    return f"{t['n']}$^{{{t['oznaka']}}}$" if t["oznaka"] else str(t["n"])


def razvrsti(tocke):
    return sorted(tocke, key=lambda t: (t["zasnova"] != "veriga", t["n"], POSKUSI.index(t["posel"])))


def tabela_zvestob(tocke):
    vrstice = []
    for t in razvrsti([t for t in tocke if not t["dd"]]):
        par = next(x for x in tocke if x["dd"] and x["zasnova"] == t["zasnova"] and x["n"] == t["n"] and x["posel"] == t["posel"])
        vrstice.append(f"{t['zasnova']} & {ime_tocke(t)} & {f_zapis(t['surovo'])} & {f_zapis(par['surovo'])} & "
                       f"{f_zapis(t['ublazeno'])} & {f_zapis(par['ublazeno'])} & "
                       f"{stevilo(t['napoved']['F_sur'])} & {stevilo(t['napoved']['F_ubl'])} \\\\")
    return vrstice


def tabela_vezij(tocke):
    vrstice = []
    for t in razvrsti([t for t in tocke if not t["dd"]]):
        lp, k = t["lastnosti_po_fazno"], t["kakovost"]
        vrstice.append(f"{t['zasnova']} & {ime_tocke(t)} & {t['pred']['globina']} & {lp['globina']} & {lp['dvokubitna']} & "
                       f"{stevilo(lp['trajanje_us'], 2)} & {stevilo(k['branje'], 4)} & {stevilo(t['surovo']['napaka_branja_povprecje'], 4)} & "
                       f"{stevilo(k['dvokubitna'], 4)} & {k['t2_us']:.0f} \\\\")
    return vrstice


def povzetek(tocke):
    pari = {}
    for t in tocke:
        pari.setdefault((t["zasnova"], t["n"], t["posel"]), {})[bool(t["dd"])] = t
    z = []
    for k, par in pari.items():
        for vrsta in ("surovo", "ublazeno"):
            razlika = par[True][vrsta]["F"] - par[False][vrsta]["F"]
            s = math.hypot(par[True][vrsta]["sigma_F"], par[False][vrsta]["sigma_F"])
            z.append((razlika / s, razlika, k, vrsta))
    z.sort(key=lambda x: x[0])
    print(f"DD: {len(z)} primerjav, navzgor {sum(x[0] > 0 for x in z)}, navzdol {sum(x[0] < 0 for x in z)}, "
          f"|z|>2: {sum(abs(x[0]) > 2 for x in z)}, največ {z[-1][:4]}, najmanj {z[0][:4]}")
    print("učinek DD na surova P in C (razlika z DD - brez DD, z):")
    for k, par in sorted(pari.items(), key=lambda x: (x[0][0] != "veriga", x[0][1], POSKUSI.index(x[0][2]))):
        d = {v: par[True]["surovo"][v] - par[False]["surovo"][v] for v in "PC"}
        s = {v: math.hypot(par[True]["surovo"][f"sigma_{v}"], par[False]["surovo"][f"sigma_{v}"]) for v in "PC"}
        print(f"  {k[0]} {k[1]} {k[2]}: dP={d['P']:+.3f} (z {d['P'] / s['P']:+.1f}), dC={d['C']:+.3f} (z {d['C'] / s['C']:+.1f})")
    for vrsta, kljuc in (("surovo", "F_sur"), ("ublazeno", "F_ubl")):
        cisto =[t for t in tocke if t["oznaka"] != "a"]
        razmerja = [t[vrsta]["F"] / t["napoved"][kljuc] for t in cisto]
        razlike = [t["napoved"][kljuc] - t[vrsta]["F"] for t in cisto]
        print(f"{vrsta}: naprava/model {min(razmerja):.2f}-{max(razmerja):.2f}, model-naprava {min(razlike):.3f}-{max(razlike):.3f}")
    for t in razvrsti([t for t in tocke if not t["dd"]]):
        print(f"{t['zasnova']} {t['n']}{t['oznaka']} G={t['napoved']['G']:.3f} D={t['napoved']['D']:.3f} A1={t['napoved']['A1']:.3f} "
              f"P={t['surovo']['P']:.3f} C={t['surovo']['C']:.3f} F-2s sur={spodnja(t, 'surovo'):.3f} ubl={spodnja(t, 'ublazeno'):.3f}")


def main():
    tocke = preberi()
    narisi(tocke)
    print("\n".join(intervali(tocke)))
    print("%% tabela zvestob")
    print("\n".join(tabela_zvestob(tocke)))
    print("%% tabela vezij")
    print("\n".join(tabela_vezij(tocke)))
    print("%% povzetek")
    povzetek(tocke)


if __name__ == "__main__":
    main()
