import argparse
import csv
from getpass import getpass
from pathlib import Path

from src.data.loader import COLONNES_UTILISATEURS, charger_comptes
from src.securite.authentification import (
    ALGORITHME, ITERATIONS, Compte, Role, calculer_empreinte, creer_compte,
    verifier_solidite,
)

FICHIER = Path("data/utilisateurs.csv")
CHAMPS = [
    "identifiant", "role", "vehicule", "algorithme", "iterations",
    "sel", "empreinte", "actif",
]


def lire() -> list[Compte]:
    """Comptes existants, ou liste vide si le fichier n'existe pas encore."""
    if not FICHIER.is_file():
        return []
    return charger_comptes(FICHIER)


def ecrire(comptes: list[Compte]) -> None:
    """Réécrit le fichier des comptes.

    Le sel et l'empreinte sont écrits en hexadécimal : un CSV ne
    transporte pas d'octets bruts.
    """
    FICHIER.parent.mkdir(parents=True, exist_ok=True)
    with FICHIER.open("w", encoding="utf-8", newline="") as flux:
        redacteur = csv.writer(flux)
        redacteur.writerow(CHAMPS)
        for compte in sorted(comptes, key=lambda c: c.identifiant):
            redacteur.writerow([
                compte.identifiant,
                compte.role.value,
                compte.vehicule,
                compte.algorithme,
                compte.iterations,
                compte.sel.hex(),
                compte.empreinte.hex(),
                "True" if compte.actif else "False",
            ])
    print(f"{len(comptes)} compte(s) enregistré(s) dans {FICHIER}")


def demander_mot_de_passe(identifiant: str) -> str:
    """Demande le mot de passe deux fois, sans l'afficher.

    La double saisie n'est pas une formalité : une faute de frappe sur un
    mot de passe qu'on ne voit pas produirait un compte auquel personne
    ne peut se connecter, et que rien ne signalerait.
    """
    for _ in range(3):
        premier = getpass("Mot de passe (la frappe ne s'affiche pas) : ")
        try:
            verifier_solidite(premier, identifiant)
        except ValueError as erreur:
            print(f"  Refusé : {erreur}")
            continue
        second = getpass("Confirmer : ")
        if premier != second:
            print("  Les deux saisies diffèrent.")
            continue
        return premier
    raise SystemExit("Trois tentatives échouées, aucun compte modifié.")


def commande_liste() -> None:
    comptes = lire()
    if not comptes:
        print("Aucun compte. Utiliser « ajouter ».")
        return
    print(f"{'IDENTIFIANT':<20} {'ROLE':<12} {'VEHICULE':<10} ETAT")
    print("-" * 54)
    for compte in sorted(comptes, key=lambda c: (c.role.value, c.identifiant)):
        etat = "actif" if compte.actif else "désactivé"
        print(
            f"{compte.identifiant:<20} {compte.role.value:<12} "
            f"{compte.vehicule or '—':<10} {etat}"
        )
    print()
    print("Aucun mot de passe n'est stocké : le fichier ne contient que des "
          "empreintes.")


def commande_ajouter(identifiant: str, role: str, vehicule: str) -> None:
    comptes = lire()
    if any(compte.identifiant == identifiant for compte in comptes):
        raise SystemExit(
            f"Le compte « {identifiant} » existe déjà. Utiliser "
            f"« motdepasse » pour en changer le mot de passe."
        )
    mot_de_passe = demander_mot_de_passe(identifiant)
    comptes.append(
        creer_compte(identifiant, mot_de_passe, Role(role), vehicule)
    )
    ecrire(comptes)


def commande_motdepasse(identifiant: str) -> None:
    comptes = lire()
    compte = next(
        (c for c in comptes if c.identifiant == identifiant), None
    )
    if compte is None:
        raise SystemExit(f"Compte inconnu : {identifiant}")
    mot_de_passe = demander_mot_de_passe(identifiant)
    # Nouveau sel à chaque changement : réutiliser l'ancien laisserait
    # deviner qu'un mot de passe a été repris à l'identique.
    remplacant = creer_compte(
        identifiant, mot_de_passe, compte.role, compte.vehicule
    )
    remplacant.actif = compte.actif
    comptes[comptes.index(compte)] = remplacant
    ecrire(comptes)


def commande_etat(identifiant: str, actif: bool) -> None:
    comptes = lire()
    compte = next((c for c in comptes if c.identifiant == identifiant), None)
    if compte is None:
        raise SystemExit(f"Compte inconnu : {identifiant}")
    compte.actif = actif
    # On ne supprime pas le compte : le journal des connexions garde des
    # traces à son nom, et une ligne effacée rendrait ces traces
    # illisibles. Désactiver suffit à interdire l'accès.
    ecrire(comptes)


def main() -> None:
    analyseur = argparse.ArgumentParser(description=__doc__)
    sous = analyseur.add_subparsers(dest="commande", required=True)

    sous.add_parser("liste", help="afficher les comptes")

    ajout = sous.add_parser("ajouter", help="créer un compte")
    ajout.add_argument("--identifiant", required=True)
    ajout.add_argument("--role", required=True,
                       choices=[role.value for role in Role])
    ajout.add_argument("--vehicule", default="",
                       help="obligatoire pour un conducteur, interdit sinon")

    motdepasse = sous.add_parser("motdepasse", help="changer un mot de passe")
    motdepasse.add_argument("--identifiant", required=True)

    for nom, actif in (("desactiver", False), ("activer", True)):
        etat = sous.add_parser(nom, help=f"{nom} un compte")
        etat.add_argument("--identifiant", required=True)
        etat.set_defaults(actif=actif)

    options = analyseur.parse_args()

    if options.commande == "liste":
        commande_liste()
    elif options.commande == "ajouter":
        commande_ajouter(options.identifiant, options.role, options.vehicule)
    elif options.commande == "motdepasse":
        commande_motdepasse(options.identifiant)
    else:
        commande_etat(options.identifiant, options.actif)


if __name__ == "__main__":
    main()
