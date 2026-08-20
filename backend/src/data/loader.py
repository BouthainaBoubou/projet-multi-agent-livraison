"""Chargement des données depuis les fichiers CSV.

Frontière unique entre le monde extérieur et le domaine métier : c'est le
seul module autorisé à lire des fichiers. Il rend des objets du domaine ;
aucun DataFrame pandas n'en sort. Le jour où les données viendront de
PostgreSQL, seul ce module changera.

Règle posée le 20/08/2026 sur les critères de classification des
commandes : **le loader n'invente aucune valeur.** Si une colonne de
critère est absente du fichier, ou si une cellule est vide, la commande
est chargée quand même mais au statut `INCOMPLETE`. Elle attend la
saisie du dispatcheur. Le fichier reste donc lisible même s'il vient d'un
ancien format — ce qui manque n'est pas comblé, il est signalé.
"""

from dataclasses import dataclass
from pathlib import Path

import pandas as pd

from src.models.commande import (
    CRITERES_CLASSIFICATION, Commande, Fragilite, TypeLivraison,
    convertir_critere,
)
from src.models.noeud import Noeud, TypeNoeud
from src.models.route import ModeTransport, ProfilTrafic, TronconRoute
from src.models.vehicule import StatutVehicule, TypeVehicule, Vehicule
from src.securite.authentification import Compte, Role

COLONNES_NOEUDS = {
    "id", "nom", "latitude", "longitude", "pays", "type_noeud",
    "duree_traitement_min",
}
# La priorité ne figure plus au contrat : elle n'est plus une donnée
# d'entrée mais le résultat de la grille de classification. Les quatre
# critères, eux, ne sont pas exigés — leur absence est un cas prévu, pas
# une erreur de fichier.
COLONNES_COMMANDES = {
    "id", "origine", "destination", "poids", "delai_minutes",
}
# Pour les véhicules, à l'inverse, l'équipement est une caractéristique
# du matériel : le transporteur la connaît toujours. Son absence est donc
# bien une erreur de fichier, signalée au chargement.
COLONNES_VEHICULES = {
    "id", "capacite_kg", "position_actuelle", "charge_actuelle_kg", "statut",
    "type_vehicule", "pays_base", "autorise_international",
    "modele", "equipement_fragile",
}
COLONNES_TRONCONS = {
    "origine", "destination", "distance_km", "temps_base_min", "mode",
    "franchit_frontiere", "cout_fixe_dh", "niveau_trafic",
    "attente_frontiere_min", "bloquee", "profil_trafic",
}
# Les comptes ne font pas partie du scénario de livraison : ils sont
# chargés à part, par `charger_comptes`. Le fichier ne contient aucun mot
# de passe — seulement le sel et l'empreinte, tous deux en hexadécimal.
COLONNES_UTILISATEURS = {
    "identifiant", "role", "vehicule", "algorithme", "iterations",
    "sel", "empreinte", "actif",
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

    def commandes_incompletes(self) -> list[Commande]:
        """Les commandes qu'il reste à classer avant toute planification."""
        return [
            commande for commande in self.commandes
            if not commande.est_complete
        ]


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


def _critere_lu(ligne, critere: str, id_commande: str):
    """Lit un critère de classification, ou rend `None` s'il est absent.

    Trois façons pour un critère de manquer, toutes traitées de la même
    manière : la colonne n'existe pas dans le fichier, la cellule est
    vide, la cellule ne contient que des espaces. Aucune n'est comblée
    par une valeur inventée.

    En revanche une valeur **présente mais inconnue** est une erreur, pas
    un manque : elle lève une exception, avec le nom de la commande et la
    liste des valeurs acceptées. Sans cela, une faute de frappe se
    traduirait par une commande silencieusement mal classée.
    """
    valeur = getattr(ligne, critere, None)
    if valeur is None or pd.isna(valeur) or not str(valeur).strip():
        return None
    try:
        return convertir_critere(critere, valeur)
    except ValueError as erreur:
        raise ValueError(f"Commande {id_commande} : {erreur}") from erreur


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

    Deux données ne sont pas lues ici :
    - le **type de livraison**, déduit des pays des noeuds par
      `_renseigner_type_livraison` une fois les quatre fichiers chargés ;
    - la **priorité**, calculée par la grille de classification à partir
      du niveau de service et du type de client. Une colonne `priorite`
      encore présente dans un vieux fichier est ignorée.
    """
    df = _lire_csv(chemin, COLONNES_COMMANDES)
    commandes = []
    for ligne in df.itertuples(index=False):
        id_commande = str(ligne.id)
        criteres = {
            critere: _critere_lu(ligne, critere, id_commande)
            for critere in CRITERES_CLASSIFICATION
        }
        commandes.append(
            Commande(
                id=id_commande,
                origine=str(ligne.origine),
                destination=str(ligne.destination),
                poids=float(ligne.poids),
                delai_minutes=int(ligne.delai_minutes),
                **criteres,
            )
        )
    return commandes


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
            modele=str(ligne.modele).strip(),
            equipement_fragile=_vers_booleen(ligne.equipement_fragile),
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
            profil_trafic=ProfilTrafic[str(ligne.profil_trafic).strip().upper()],
            niveau_trafic=float(ligne.niveau_trafic),
            attente_frontiere_min=float(ligne.attente_frontiere_min),
            bloquee=_vers_booleen(ligne.bloquee),
        )
        for ligne in df.itertuples(index=False)
    ]


def charger_comptes(chemin: str | Path) -> list[Compte]:
    """Lit le fichier des utilisateurs et retourne une liste de comptes.

    Chargé séparément des quatre CSV du scénario : un compte n'est pas
    une donnée de livraison, et il n'a pas à voyager avec elles. Le
    fichier ne contient **aucun mot de passe**, seulement le sel et
    l'empreinte ; il ne permet donc pas de se connecter à la place de
    quelqu'un, seulement de vérifier qu'un mot de passe présenté est le
    bon.

    Le rattachement conducteur → véhicule n'est pas contrôlé ici contre
    `vehicules.csv` : le module de sécurité ne connaît pas la flotte, et
    c'est voulu. Un conducteur dont le véhicule aurait disparu se verra
    simplement refuser toutes les tournées.
    """
    chemin = Path(chemin)
    df = _lire_csv(chemin, COLONNES_UTILISATEURS)

    comptes = []
    for ligne in df.itertuples(index=False):
        vehicule = "" if pd.isna(ligne.vehicule) else str(ligne.vehicule).strip()
        identifiant = str(ligne.identifiant).strip()
        try:
            role = Role(str(ligne.role).strip().lower())
        except ValueError as erreur:
            raise ValueError(
                f"Compte {identifiant} : rôle '{ligne.role}' inconnu "
                f"(attendu 'dispatcheur' ou 'conducteur')"
            ) from erreur
        comptes.append(
            Compte(
                identifiant=identifiant,
                role=role,
                sel=bytes.fromhex(str(ligne.sel).strip()),
                empreinte=bytes.fromhex(str(ligne.empreinte).strip()),
                vehicule=vehicule,
                algorithme=str(ligne.algorithme).strip(),
                iterations=int(ligne.iterations),
                actif=_vers_booleen(ligne.actif),
            )
        )

    identifiants = [compte.identifiant for compte in comptes]
    doublons = {i for i in identifiants if identifiants.count(i) > 1}
    if doublons:
        raise ValueError(f"Identifiants en double : {sorted(doublons)}")
    if not any(compte.role is Role.DISPATCHEUR and compte.actif for compte in comptes):
        raise ValueError(
            "Aucun dispatcheur actif : plus personne ne pourrait planifier"
        )
    return comptes


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


def _verifier_faisabilite_fragile(donnees: DonneesLivraison) -> None:
    """Vérifie qu'un lot très fragile a au moins un véhicule pour le prendre.

    Ne concerne que les commandes déjà classées : une commande incomplète
    n'a pas encore de fragilité, il n'y a rien à vérifier. Contrôle de
    dimensionnement, au même titre que celui du transport international —
    il vaut mieux l'apprendre au chargement qu'après une planification
    qui rejette tout sans expliquer pourquoi.
    """
    exige_equipement = [
        commande for commande in donnees.commandes
        if commande.fragilite is Fragilite.TRES_FRAGILE
    ]
    if not exige_equipement:
        return
    if not any(vehicule.equipement_fragile for vehicule in donnees.vehicules):
        raise ValueError(
            f"Le scénario contient {len(exige_equipement)} commande(s) très "
            f"fragile(s) mais aucun véhicule équipé (suspension pneumatique "
            f"et arrimage) : ces commandes ne pourraient jamais être servies"
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

    Le chargement **réussit** même si des commandes sont incomplètes :
    c'est la planification, et elle seule, qui refusera de démarrer.
    Faire échouer le chargement empêcherait le dispatcheur d'ouvrir son
    écran pour justement compléter ce qui manque.
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
    _verifier_faisabilite_fragile(donnees)
    return donnees
