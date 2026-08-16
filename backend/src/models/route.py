"""Modèle représentant un tronçon du réseau routier."""

from dataclasses import dataclass


@dataclass
class TronconRoute:
    """Un segment de route entre deux noeuds voisins.

    Un itinéraire complet est une suite de tronçons ; cette classe ne
    représente qu'un seul segment. Structure de données passive : elle
    porte l'information et garantit sa propre cohérence, mais ne contient
    aucune logique métier.
    """

    # --- Identité ---
    # Le couple (origine, destination) identifie le tronçon.
    origine: str                # identifiant du noeud de départ
    destination: str            # identifiant du noeud d'arrivée

    # --- Données métier ---
    distance_km: float          # longueur du tronçon
    temps_base_min: float       # temps de trajet sans trafic

    # --- État courant ---
    niveau_trafic: float = 1.0  # multiplicateur : 1.0 fluide, 2.5 embouteillage
    bloquee: bool = False       # tronçon impraticable (scénario 3)

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

    @property
    def temps_reel_min(self) -> float:
        """Temps de trajet effectif, trafic inclus."""
        return self.temps_base_min * self.niveau_trafic

    @property
    def praticable(self) -> bool:
        """Un tronçon bloqué ne peut être emprunté par aucun véhicule."""
        return not self.bloquee