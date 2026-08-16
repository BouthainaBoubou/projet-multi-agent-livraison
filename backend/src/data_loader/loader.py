"""Chargement des données depuis les fichiers CSV.

Frontière unique entre le monde extérieur et le domaine métier : c'est le
seul module autorisé à lire des fichiers. Il rend des objets du domaine ;
aucun DataFrame pandas n'en sort. Le jour où les données viendront de
PostgreSQL, seul ce module changera.
"""

from dataclasses import dataclass
from pathlib import Path

import pandas as pd

from src.models.commande import Commande, Priorite
from src.models.noeud import Noeud
from src.models.route import TronconRoute
from src.models.vehicule import StatutVehicule, Vehicule



COLONNES_NOEUDS = {"id", "nom", "latitude", "longitude"}
COLONNES_COMMANDES = {"id", "destination", "poids", "priorite", "delai_minutes"}
COLONNES_VEHICULES = {
    "id", "capacite_kg", "position_actuelle", "charge_actuelle_kg", "statut"
}
COLONNES_TRONCONS = {
    "origine", "destination", "distance_km", "temps_base_min",
    "niveau_trafic", "bloquee"
}


@dataclass
class DonneesLivraison:
    """Regroupe les quatre jeux de données d'un scénario."""

    noeuds: list[Noeud]
    commandes: list[Commande]
    vehicules: list[Vehicule]
    troncons: list[TronconRoute]


def _lire_csv(chemin: Path, colonnes_requises: set[str]) -> pd.DataFrame:
    """Lit un CSV et vérifie qu'il respecte son contrat de colonnes.

    Factorisation des trois vérifications communes aux quatre fichiers :
    le fichier existe, il n'est pas vide, il contient les colonnes
    attendues. Les colonnes en trop ne sont pas une erreur.
    """
    if not chemin.is_file():
        raise FileNotFoundError(f"Fichier introuvable : {chemin}")

    df = pd.read_csv(chemin)

    manquantes = colonnes_requises - set(df.columns)
    if manquantes:
        raise ValueError(
            f"{chemin.name} : colonnes manquantes {sorted(manquantes)}"
        )
    if df.empty:
        raise ValueError(f"{chemin.name} : aucune ligne de données")

    return df


def charger_noeuds(chemin: Path) -> list[Noeud]:
    """Lit le CSV des noeuds et retourne une liste d'objets Noeud."""
    df = _lire_csv(chemin, COLONNES_NOEUDS)
    return [
        Noeud(
            id=str(ligne.id),
            nom=str(ligne.nom),
            latitude=float(ligne.latitude),
            longitude=float(ligne.longitude),
        )
        for ligne in df.itertuples(index=False)
    ]


def charger_commandes(chemin: Path) -> list[Commande]:
    """Lit le CSV des commandes et retourne une liste d'objets Commande."""
    df = _lire_csv(chemin, COLONNES_COMMANDES)
    return [
        Commande(
            id=str(ligne.id),
            destination=str(ligne.destination),
            poids=float(ligne.poids),
            priorite=Priorite[str(ligne.priorite).strip().upper()],
            delai_minutes=int(ligne.delai_minutes),
        )
        for ligne in df.itertuples(index=False)
    ]


def charger_vehicules(chemin: Path) -> list[Vehicule]:
    """Lit le CSV des véhicules et retourne une liste d'objets Vehicule."""
    df = _lire_csv(chemin, COLONNES_VEHICULES)
    return [
        Vehicule(
            id=str(ligne.id),
            capacite_kg=float(ligne.capacite_kg),
            position_actuelle=str(ligne.position_actuelle),
            charge_actuelle_kg=float(ligne.charge_actuelle_kg),
            statut=StatutVehicule[str(ligne.statut).strip().upper()],
        )
        for ligne in df.itertuples(index=False)
    ]


def charger_troncons(chemin: Path) -> list[TronconRoute]:
    """Lit le CSV des routes et retourne une liste d'objets TronconRoute."""
    df = _lire_csv(chemin, COLONNES_TRONCONS)
    return [
        TronconRoute(
            origine=str(ligne.origine),
            destination=str(ligne.destination),
            distance_km=float(ligne.distance_km),
            temps_base_min=float(ligne.temps_base_min),
            niveau_trafic=float(ligne.niveau_trafic),
            bloquee=str(ligne.bloquee).strip().lower() == "true",
        )
        for ligne in df.itertuples(index=False)
    ]


def _verifier_unicite_ids(donnees: DonneesLivraison) -> None:
    """Vérifie qu'aucun identifiant n'est utilisé deux fois."""
    for libelle, elements in (
        ("noeud", donnees.noeuds),
        ("commande", donnees.commandes),
        ("véhicule", donnees.vehicules),
    ):
        ids = [element.id for element in elements]
        doublons = {valeur for valeur in ids if ids.count(valeur) > 1}
        if doublons:
            raise ValueError(
                f"Identifiants de {libelle} en double : {sorted(doublons)}"
            )


def _verifier_coherence(donnees: DonneesLivraison) -> None:
    """Vérifie que tous les identifiants de noeuds référencés existent.

    Chaque modèle garantit sa cohérence interne ; cette fonction garantit
    la cohérence relationnelle entre les fichiers. C'est l'équivalent
    manuel d'une contrainte de clé étrangère en base de données.
    """
    ids_noeuds = {noeud.id for noeud in donnees.noeuds}

    for commande in donnees.commandes:
        if commande.destination not in ids_noeuds:
            raise ValueError(
                f"Commande {commande.id} : destination inconnue "
                f"'{commande.destination}'"
            )

    for vehicule in donnees.vehicules:
        if vehicule.position_actuelle not in ids_noeuds:
            raise ValueError(
                f"Véhicule {vehicule.id} : position inconnue "
                f"'{vehicule.position_actuelle}'"
            )

    for troncon in donnees.troncons:
        if troncon.origine not in ids_noeuds:
            raise ValueError(
                f"Tronçon {troncon.origine} -> {troncon.destination} : "
                f"origine inconnue"
            )
        if troncon.destination not in ids_noeuds:
            raise ValueError(
                f"Tronçon {troncon.origine} -> {troncon.destination} : "
                f"destination inconnue"
            )


def charger_tout(dossier: str | Path) -> DonneesLivraison:
    """Charge les quatre fichiers d'un scénario et valide leur cohérence.

    Le dossier est un paramètre : c'est ce qui permet de changer de
    scénario sans toucher au code.
    """
    dossier = Path(dossier)
    if not dossier.is_dir():
        raise FileNotFoundError(f"Dossier de données introuvable : {dossier}")

    donnees = DonneesLivraison(
        noeuds=charger_noeuds(dossier / "noeuds.csv"),
        commandes=charger_commandes(dossier / "commandes.csv"),
        vehicules=charger_vehicules(dossier / "vehicules.csv"),
        troncons=charger_troncons(dossier / "routes.csv"),
    )
    _verifier_unicite_ids(donnees)
    _verifier_coherence(donnees)
    return donnees