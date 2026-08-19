"""Modèle représentant un tronçon du réseau de transport."""

from dataclasses import dataclass
from enum import Enum


class ModeTransport(Enum):
    """Mode de transport d'un tronçon.

    Le mode change ce qui fait varier le temps de parcours : la
    congestion pour la route, l'horaire de départ et l'attente
    d'embarquement pour le maritime.
    """
    ROUTIER = "routier"
    MARITIME = "maritime"   # traversée par ferry, ex. Tanger Med - Algeciras


@dataclass
class TronconRoute:
    """Un segment reliant deux noeuds voisins.

    Un itinéraire complet est une suite de tronçons ; cette classe ne
    représente qu'un seul segment. Structure de données passive : elle
    porte l'information et garantit sa propre cohérence, mais ne contient
    aucune logique métier.
    """

    # --- Identité ---
    # Le couple (origine, destination) identifie le tronçon.
    origine: str                # identifiant du noeud de départ
    destination: str            # identifiant du noeud d'arrivée

    # --- Données métier (référence, ne changent pas en cours de journée) ---
    distance_km: float          # longueur du tronçon
    temps_base_min: float       # temps de trajet sans perturbation
    mode: ModeTransport = ModeTransport.ROUTIER
    franchit_frontiere: bool = False    # le tronçon change de pays
    cout_fixe_dh: float = 0.0   # péages autoroutiers, billet de ferry

    # --- État courant (modifié par le TrafficAgent) ---
    niveau_trafic: float = 1.0  # multiplicateur : 1.0 fluide, 2.5 saturé
    attente_frontiere_min: float = 0.0  # file d'attente douane / embarquement
    bloquee: bool = False       # tronçon impraticable (accident, fermeture)

    def __post_init__(self) -> None:
        """Vérifie les invariants juste après la construction de l'objet.

        Une clause de garde par règle : chaque échec possible a son propre
        message, indiquant quoi, où et quelle valeur a été reçue.
        """
        if not self.origine:
            raise ValueError("Tronçon : origine vide")
        if not self.destination:
            raise ValueError(
                f"Tronçon partant de {self.origine} : destination vide"
            )
        if self.origine == self.destination:
            raise ValueError(
                f"Tronçon {self.origine} -> {self.destination} : l'origine "
                f"et la destination doivent être différentes"
            )
        if self.distance_km <= 0:
            raise ValueError(
                f"Tronçon {self.origine} -> {self.destination} : la distance "
                f"doit être strictement positive (reçu : {self.distance_km})"
            )
        if self.temps_base_min <= 0:
            raise ValueError(
                f"Tronçon {self.origine} -> {self.destination} : le temps de "
                f"base doit être strictement positif "
                f"(reçu : {self.temps_base_min})"
            )
        if self.niveau_trafic < 1.0:
            raise ValueError(
                f"Tronçon {self.origine} -> {self.destination} : le niveau de "
                f"trafic doit être supérieur ou égal à 1.0 "
                f"(reçu : {self.niveau_trafic})"
            )
        if self.attente_frontiere_min < 0:
            raise ValueError(
                f"Tronçon {self.origine} -> {self.destination} : l'attente à "
                f"la frontière ne peut pas être négative "
                f"(reçu : {self.attente_frontiere_min})"
            )
        if self.cout_fixe_dh < 0:
            raise ValueError(
                f"Tronçon {self.origine} -> {self.destination} : le coût fixe "
                f"ne peut pas être négatif (reçu : {self.cout_fixe_dh})"
            )
        # Une traversée maritime ne subit pas la congestion routière : son
        # aléa est l'attente d'embarquement, pas le trafic.
        if self.mode is ModeTransport.MARITIME and self.niveau_trafic != 1.0:
            raise ValueError(
                f"Tronçon {self.origine} -> {self.destination} : un tronçon "
                f"maritime ne peut pas porter de niveau de trafic "
                f"(reçu : {self.niveau_trafic}) ; utiliser "
                f"attente_frontiere_min"
            )
        # Une attente de franchissement n'a de sens que sur un tronçon qui
        # franchit effectivement une frontière.
        if self.attente_frontiere_min > 0 and not self.franchit_frontiere:
            raise ValueError(
                f"Tronçon {self.origine} -> {self.destination} : attente de "
                f"franchissement renseignée sur un tronçon qui ne franchit "
                f"aucune frontière"
            )

    @property
    def temps_reel_min(self) -> float:
        """Temps de parcours effectif, perturbations incluses.

        Trois termes de nature différente : le temps de roulage, le
        facteur de congestion qui le multiplie, et l'attente de
        franchissement qui s'y ajoute sans dépendre de la distance.
        """
        return self.temps_base_min * self.niveau_trafic + self.attente_frontiere_min

    @property
    def praticable(self) -> bool:
        """Un tronçon bloqué ne peut être emprunté par aucun véhicule."""
        return not self.bloquee

    @property
    def international(self) -> bool:
        """Vrai si emprunter ce tronçon fait changer de pays."""
        return self.franchit_frontiere