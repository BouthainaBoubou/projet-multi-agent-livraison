"""Modèle représentant un véhicule de livraison."""

from dataclasses import dataclass
from enum import Enum


class StatutVehicule(Enum):
    """État courant d'un véhicule.

    Source unique de vérité pour la disponibilité : on ne stocke pas
    d'attribut `disponible` séparé, il est déduit du statut.
    """
    AU_DEPOT = "au_depot"       # disponible, prêt à recevoir une tournée
    EN_TOURNEE = "en_tournee"   # en cours de livraison
    EN_PANNE = "en_panne"       # indisponible (scénario 2)


@dataclass
class Vehicule:
    """Un véhicule de livraison.

    Structure de données passive : elle porte l'information et garantit
    sa propre cohérence, mais ne contient aucune logique métier.
    """

    # --- Identité ---
    id: str                     # ex. "V001", unique

    # --- Données métier ---
    capacite_kg: float          # charge maximale transportable
    position_actuelle: str      # identifiant du noeud où se trouve le véhicule

    # --- État courant ---
    charge_actuelle_kg: float = 0.0
    statut: StatutVehicule = StatutVehicule.AU_DEPOT

    def __post_init__(self) -> None:
        """Vérifie les invariants juste après la construction de l'objet.

        Une clause de garde par règle : chaque échec possible a son propre
        message, indiquant quoi, où et quelle valeur a été reçue.
        """
        if self.capacite_kg <= 0:
            raise ValueError(
                f"Véhicule {self.id} : la capacité doit être strictement "
                f"positive (reçu : {self.capacite_kg})"
            )
        if self.charge_actuelle_kg < 0:
            raise ValueError(
                f"Véhicule {self.id} : la charge ne peut pas être négative "
                f"(reçu : {self.charge_actuelle_kg})"
            )
        if self.charge_actuelle_kg > self.capacite_kg:
            raise ValueError(
                f"Véhicule {self.id} : charge {self.charge_actuelle_kg} kg "
                f"supérieure à la capacité {self.capacite_kg} kg"
            )
        if not self.position_actuelle:
            raise ValueError(f"Véhicule {self.id} : position vide")

    @property
    def capacite_restante(self) -> float:
        """Charge supplémentaire acceptable, en kilogrammes."""
        return self.capacite_kg - self.charge_actuelle_kg

    @property
    def disponible(self) -> bool:
        """Un véhicule est disponible s'il est au dépôt, prêt à partir."""
        return self.statut == StatutVehicule.AU_DEPOT