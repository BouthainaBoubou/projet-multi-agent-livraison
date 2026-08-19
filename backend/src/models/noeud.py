"""Modèle représentant un point du réseau de livraison.

Périmètre national et international : un noeud n'est plus seulement un
point de la ville, il appartient à un pays et joue un rôle précis dans la
chaîne (hub, agence régionale, client, port, poste frontière).
"""

from dataclasses import dataclass
from enum import Enum


class TypeNoeud(Enum):
    """Rôle d'un noeud dans la chaîne de transport.

    Le rôle n'est pas décoratif : il conditionne ce que le noeud impose
    au véhicule qui s'y arrête (temps de traitement, formalités).
    """
    HUB = "hub"                     # plateforme centrale, départ des tournées
    AGENCE = "agence"               # agence régionale, point de rupture de charge
    CLIENT = "client"               # point de livraison final
    PORT = "port"                   # terminal maritime (embarquement / débarquement)
    POSTE_FRONTIERE = "poste_frontiere"  # passage terrestre avec formalités


@dataclass
class Noeud:
    """Un point géographique du réseau de livraison.

    Structure de données passive : elle porte l'information et garantit
    sa propre cohérence, mais ne contient aucune logique métier.
    """

    # --- Identité ---
    id: str

    # --- Données métier ---
    nom: str                # libellé lisible, ex. "Casablanca (hub)"
    latitude: float         # degrés décimaux, entre -90 et 90
    longitude: float        # degrés décimaux, entre -180 et 180
    pays: str               # code ISO 3166-1 alpha-2, ex. "MA", "ES", "FR"
    type_noeud: TypeNoeud = TypeNoeud.CLIENT

    # Temps d'immobilisation imposé par le noeud lui-même, en minutes :
    # manutention pour un entrepôt, formalités et attente pour un port ou
    # un poste frontière. Distinct du temps de trajet, qui appartient au
    # tronçon.
    duree_traitement_min: float = 0.0

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
        if len(self.pays) != 2 or not self.pays.isalpha() or not self.pays.isupper():
            raise ValueError(
                f"Noeud {self.id} : code pays invalide, attendu deux lettres "
                f"majuscules ISO 3166-1 (reçu : '{self.pays}')"
            )
        if self.duree_traitement_min < 0:
            raise ValueError(
                f"Noeud {self.id} : la durée de traitement ne peut pas être "
                f"négative (reçu : {self.duree_traitement_min})"
            )
        if self.est_point_de_passage and self.duree_traitement_min <= 0:
            raise ValueError(
                f"Noeud {self.id} : un {self.type_noeud.value} impose "
                f"forcément une durée de traitement strictement positive "
                f"(formalités, attente) — reçu : {self.duree_traitement_min}"
            )

    @property
    def est_point_de_passage(self) -> bool:
        """Vrai si le noeud est un point de franchissement de frontière."""
        return self.type_noeud in (TypeNoeud.PORT, TypeNoeud.POSTE_FRONTIERE)

    @property
    def est_depart_de_tournee(self) -> bool:
        """Vrai si des tournées peuvent partir de ce noeud."""
        return self.type_noeud in (TypeNoeud.HUB, TypeNoeud.AGENCE)