"""Modèle représentant un point du réseau de livraison."""

from dataclasses import dataclass


@dataclass
class Noeud:
    """Un point géographique du réseau : dépôt ou zone de livraison.

    Structure de données passive : elle porte l'information et garantit
    sa propre cohérence, mais ne contient aucune logique métier.
    """

    # --- Identité ---
    id: str                

    # --- Données métier ---
    nom: str                # libellé lisible, ex. "Dépôt central"
    latitude: float         # degrés décimaux, entre -90 et 90
    longitude: float        # degrés décimaux, entre -180 et 180

    def __post_init__(self) -> None:
        """Vérifie les invariants juste après la construction de l'objet."""
        if not self.id:
            raise ValueError("Noeud : identifiant vide")
        if not self.nom:
            raise ValueError(f"Noeud {self.id} : nom vide")
        if not -90 <= self.latitude <= 90:
            raise ValueError(
                f"Noeud {self.id} : latitude hors bornes, attendu entre -90 "
                f"et 90 (reçu : {self.latitude})"
            )
        if not -180 <= self.longitude <= 180:
            raise ValueError(
                f"Noeud {self.id} : longitude hors bornes, attendu entre -180 "
                f"et 180 (reçu : {self.longitude})"
            )