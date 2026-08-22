import argparse

from src.data.loader import charger_tout
from src.services.geometrie import ServiceGeometrie


def main() -> None:
    analyseur = argparse.ArgumentParser(description=__doc__)
    analyseur.add_argument("--cle-api", default=None)
    analyseur.add_argument("--fournisseur", default="ors", choices=["ors", "osrm"])
    analyseur.add_argument("--etat", action="store_true",
                           help="affiche l'état du cache sans rien télécharger")
    options = analyseur.parse_args()

    donnees = charger_tout("data")
    service = ServiceGeometrie(
        donnees.noeuds, donnees.troncons,
        cle_api=options.cle_api, fournisseur=options.fournisseur,
    )

    if options.etat:
        reels = sum(
            1 for entree in service.cache.values()
            if entree["source"] not in ("droit",)
        )
        print(f"Cache : {len(service.cache)} tronçon(s) mémorisé(s), "
              f"dont {reels} en géométrie réelle, sur "
              f"{len(donnees.troncons)} tronçons du réseau.")
        return

    if options.fournisseur == "ors" and not options.cle_api:
        print("Aucune clé d'API : tous les tracés seront approximatifs.")
        print("Créez une clé sur openrouteservice.org, ou utilisez "
              "--fournisseur osrm.\n")

    approximatifs = []
    for troncon in donnees.troncons:
        trace = service.tracer(troncon.origine, troncon.destination)
        etat = "réel" if not trace.approximatif else "APPROXIMATIF"
        if trace.approximatif:
            approximatifs.append(f"{troncon.origine}-{troncon.destination}")
        print(f"  {troncon.origine:>4} → {troncon.destination:<4} "
              f"{len(trace.points):>5} points  [{trace.source}] {etat}")

    service.sauver_cache()

    print(f"\n{len(donnees.troncons)} tronçons traités, "
          f"{service.appels_reseau} appel(s) réseau.")
    print(f"Cache écrit dans data/geometries.json")
    if approximatifs:
        print(f"Encore approximatifs : {', '.join(approximatifs)}")
        print("(La traversée maritime le restera toujours : "
              "il n'y a pas de route sur la mer.)")


if __name__ == "__main__":
    main()