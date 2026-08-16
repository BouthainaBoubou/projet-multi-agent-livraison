"""Modèle représentant une commande de livraison."""

from dataclasses import dataclass, field
from enum import Enum


class Priorite(Enum):
    """Niveau d'urgence d'une commande.

    La valeur numérique est volontairement croissante avec l'urgence :
    elle servira plus tard à trier ou à pondérer dans l'optimisation.
    """
    BASSE = 1
    NORMALE = 2
    HAUTE = 3


class StatutCommande(Enum):
    """Cycle de vie d'une commande."""
    EN_ATTENTE = "en_attente"   # créée, pas encore affectée à un véhicule
    ASSIGNEE = "assignee"       # affectée par l'agent d'optimisation
    EN_COURS = "en_cours"       # le véhicule est en route
    LIVREE = "livree"           # terminée dans les délais ou non
    ECHOUEE = "echouee"         # impossible à livrer


@dataclass
class Commande:
    """Une commande à livrer.

    Structure de données passive : elle porte l'information et garantit
    sa propre cohérence, mais ne contient aucune logique métier.
    """

    # --- Identité ---
    id: str                     

    # --- Données métier ---
    destination: str            # identifiant du noeud de livraison, ex. "Z3"
    poids: float                # en kilogrammes
    priorite: Priorite
    delai_minutes: int          # délai max en minutes depuis l'instant t0

    # --- État courant ---
   
    statut: StatutCommande = field(default=StatutCommande.EN_ATTENTE)
    vehicule_assigne: str | None = field(default=None)

    def __post_init__(self) -> None:
        """Vérifie les invariants juste après la construction de l'objet.

        Appelée automatiquement par la dataclass. Si une règle est violée,
        on lève une exception immédiatement (principe fail fast).
        """
        if self.poids <= 0:
            raise ValueError(
                f"Commande {self.id} : le poids doit être strictement positif "
                f"(reçu : {self.poids})"
            )
        if self.delai_minutes <= 0:
            raise ValueError(
                f"Commande {self.id} : le délai doit être strictement positif "
                f"(reçu : {self.delai_minutes})"
            )
        if not self.destination:
            raise ValueError(f"Commande {self.id} : destination vide")

    @property
    def est_urgente(self) -> bool:
        """Donnée dérivée : ne dépend que des attributs de l'objet."""
        return self.priorite == Priorite.HAUTE