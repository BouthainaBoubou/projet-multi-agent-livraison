"""Chargement des données depuis les fichiers CSV.

Frontière unique entre le monde extérieur et le domaine métier : c'est le
seul module autorisé à lire des fichiers. Il rend des objets du domaine ;
aucun DataFrame pandas n'en sort. Le jour où les données viendront de
PostgreSQL, seul ce module changera.
"""

from dataclasses import dataclass
from pathlib import Path

import pandas as pd

from src.models.commande import Commande, Priorite, TypeLivraison
from src.models.noeud import Noeud, TypeNoeud
from src.models.route import ModeTransport, TronconRoute
from src.models.vehicule import StatutVehicule, TypeVehicule, Vehicule

COLONNES_NOEUDS = {
    "id", "nom", "latitude", "longitude", "pays", "type_noeud",
    "duree_traitement_min",
}
COLONNES_COMMANDES = {
    "id", "origine", "destination", "poids", "priorite", "delai_minutes",
}
COLONNES_VEHICULES = {
    "id", "capacite_kg", "position_actuelle", "charge_actuelle_kg", "statut",
    "type_vehicule", "pays_base", "autorise_international",
}
COLONNES_TRONCONS = {
    "origine", "destination", "distance_km", "temps_base_min", "mode",
    "franchit_frontiere", "cout_fixe_dh", "niveau_trafic",
    "attente_frontiere_min", "bloquee",
}


@dataclass
class DonneesLivraison:
    """Regroupe les quatre jeux de données d'un scénario."""

    noeuds: list[Noeud]
    commandes: list[Commande]
    vehicules: list[Vehicule]
    troncons: list[TronconRoute]

    def pays_par_noeud(self) -> dict[str, str]:
        """Table de correspondance identifiant de noeud -> code pays."""
        return {noeud.id: noeud.pays for noeud in self.noeuds}


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


def _vers_booleen(valeur: object) -> bool:
    """Convertit une valeur de CSV en booléen.

    Un CSV ne connaît que du texte : pandas rend tantôt un booléen,
    tantôt la chaîne "True". Une seule fonction tranche, pour que la
    règle de conversion ne soit pas dispersée dans quatre lecteurs.
    """
    return str(valeur).strip().lower() in {"true", "1", "oui", "yes"}


def charger_noeuds(chemin: Path) -> list[Noeud]:
    """Lit le CSV des noeuds et retourne une liste d'objets Noeud."""
    df = _lire_csv(chemin, COLONNES_NOEUDS)
    return [
        Noeud(
            id=str(ligne.id),
            nom=str(ligne.nom),
            latitude=float(ligne.latitude),
            longitude=float(ligne.longitude),
            pays=str(ligne.pays).strip().upper(),
            type_noeud=TypeNoeud[str(ligne.type_noeud).strip().upper()],
            duree_traitement_min=float(ligne.duree_traitement_min),
        )
        for ligne in df.itertuples(index=False)
    ]


def charger_commandes(chemin: Path) -> list[Commande]:
    """Lit le CSV des commandes et retourne une liste d'objets Commande.

    Le type de livraison n'est pas lu : il est déduit des pays des noeuds
    par `_renseigner_type_livraison`, une fois les quatre fichiers chargés.
    """
    df = _lire_csv(chemin, COLONNES_COMMANDES)
    return [
        Commande(
            id=str(ligne.id),
            origine=str(ligne.origine),
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
            type_vehicule=TypeVehicule[str(ligne.type_vehicule).strip().upper()],
            pays_base=str(ligne.pays_base).strip().upper(),
            autorise_international=_vers_booleen(ligne.autorise_international),
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
            mode=ModeTransport[str(ligne.mode).strip().upper()],
            franchit_frontiere=_vers_booleen(ligne.franchit_frontiere),
            cout_fixe_dh=float(ligne.cout_fixe_dh),
            niveau_trafic=float(ligne.niveau_trafic),
            attente_frontiere_min=float(ligne.attente_frontiere_min),
            bloquee=_vers_booleen(ligne.bloquee),
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

    # Le réseau est un graphe non orienté : un tronçon y est identifié par
    # la paire de ses extrémités, sans ordre. Saisir Casablanca -> Rabat
    # puis Rabat -> Casablanca crée deux arêtes concurrentes dont une
    # seule serait retenue, silencieusement.
    paires = [
        frozenset((troncon.origine, troncon.destination))
        for troncon in donnees.troncons
    ]
    doublons_troncons = {
        tuple(sorted(paire)) for paire in paires if paires.count(paire) > 1
    }
    if doublons_troncons:
        raise ValueError(
            f"Tronçons en double (graphe non orienté) : "
            f"{sorted(doublons_troncons)}"
        )


def _verifier_coherence(donnees: DonneesLivraison) -> None:
    """Vérifie que tous les identifiants de noeuds référencés existent.

    Chaque modèle garantit sa cohérence interne ; cette fonction garantit
    la cohérence relationnelle entre les fichiers. C'est l'équivalent
    manuel d'une contrainte de clé étrangère en base de données.
    """
    ids_noeuds = {noeud.id for noeud in donnees.noeuds}

    for commande in donnees.commandes:
        if commande.origine not in ids_noeuds:
            raise ValueError(
                f"Commande {commande.id} : origine inconnue "
                f"'{commande.origine}'"
            )
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


def _verifier_coherence_internationale(donnees: DonneesLivraison) -> None:
    """Vérifie les règles propres au périmètre international.

    Trois erreurs de saisie sont possibles et silencieuses si on ne les
    cherche pas : un tronçon déclaré transfrontalier alors qu'il relie
    deux noeuds du même pays, l'inverse, et un scénario où aucune
    commande internationale ne pourrait jamais être servie.
    """
    pays = donnees.pays_par_noeud()

    for troncon in donnees.troncons:
        change_de_pays = pays[troncon.origine] != pays[troncon.destination]
        if change_de_pays and not troncon.franchit_frontiere:
            raise ValueError(
                f"Tronçon {troncon.origine} -> {troncon.destination} : relie "
                f"{pays[troncon.origine]} et {pays[troncon.destination]} mais "
                f"n'est pas déclaré transfrontalier"
            )
        if troncon.franchit_frontiere and not change_de_pays:
            raise ValueError(
                f"Tronçon {troncon.origine} -> {troncon.destination} : "
                f"déclaré transfrontalier alors que les deux noeuds sont en "
                f"{pays[troncon.origine]}"
            )

    a_des_commandes_internationales = any(
        commande.est_internationale for commande in donnees.commandes
    )
    aucun_vehicule_international = not any(
        vehicule.autorise_international for vehicule in donnees.vehicules
    )
    if a_des_commandes_internationales and aucun_vehicule_international:
        raise ValueError(
            "Le scénario contient des commandes internationales mais aucun "
            "véhicule autorisé à franchir la frontière : problème infaisable"
        )


def _renseigner_type_livraison(donnees: DonneesLivraison) -> None:
    """Déduit le type de chaque commande des pays de ses deux extrémités.

    Le type de livraison est une donnée dérivée : la calculer ici, en un
    seul endroit, évite qu'un agent la recalcule différemment ailleurs.
    """
    pays = donnees.pays_par_noeud()
    for commande in donnees.commandes:
        commande.type_livraison = (
            TypeLivraison.NATIONALE
            if pays[commande.origine] == pays[commande.destination]
            else TypeLivraison.INTERNATIONALE
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
    _renseigner_type_livraison(donnees)
    _verifier_coherence_internationale(donnees)
    return donnees