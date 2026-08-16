"""Point d'entrée de vérification : charge un scénario et affiche un résumé.

Ce fichier ne contient aucune logique métier. Il sert uniquement à
vérifier manuellement que le chargement fonctionne.
"""

from pathlib import Path

from src.data_loader.loader import DonneesLivraison, charger_tout

DOSSIER_DONNEES = Path(__file__).parent / "data"


def afficher_resume(donnees: DonneesLivraison) -> None:
    """Affiche les chiffres clés du scénario chargé."""
    poids_total = sum(commande.poids for commande in donnees.commandes)
    capacite_totale = sum(v.capacite_kg for v in donnees.vehicules)
    urgentes = sum(1 for c in donnees.commandes if c.est_urgente)
    disponibles = sum(1 for v in donnees.vehicules if v.disponible)

    print("=" * 52)
    print(f"  Scénario chargé depuis : {DOSSIER_DONNEES}")
    print("=" * 52)
    print(f"  Noeuds          : {len(donnees.noeuds)}")
    print(f"  Tronçons        : {len(donnees.troncons)}")
    print(f"  Commandes       : {len(donnees.commandes)}"
          f"  (dont {urgentes} urgentes)")
    print(f"  Véhicules       : {len(donnees.vehicules)}"
          f"  (dont {disponibles} disponibles)")
    print("-" * 52)
    print(f"  Poids total     : {poids_total:.0f} kg")
    print(f"  Capacité totale : {capacite_totale:.0f} kg")

    if poids_total > capacite_totale:
        print("  /!\\ Charge supérieure à la capacité : "
              "plusieurs tournées seront nécessaires.")
    else:
        marge = 100 * (1 - poids_total / capacite_totale)
        print(f"  Marge disponible : {marge:.0f} %")
    print("=" * 52)


def main() -> None:
    """Charge les données et affiche le résumé, ou l'erreur rencontrée."""
    try:
        donnees = charger_tout(DOSSIER_DONNEES)
    except (FileNotFoundError, ValueError) as erreur:
        print(f"\n[ERREUR DE CHARGEMENT] {erreur}\n")
        return

    afficher_resume(donnees)


if __name__ == "__main__":
    main()