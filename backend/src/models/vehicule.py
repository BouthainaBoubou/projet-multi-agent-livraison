"""Modèle représentant un véhicule de livraison."""

from dataclasses import dataclass
from enum import Enum

# Durée maximale de conduite journalière, en minutes (9 heures).
# À l'échelle nationale et internationale, c'est cette limite — et non la
# capacité — qui borne le plus souvent une tournée.
CONDUITE_JOURNALIERE_MAX_MIN: float = 540.0

# Durée maximale de conduite continue avant pause obligatoire (4 h 30).
CONDUITE_CONTINUE_MAX_MIN: float = 270.0


class StatutVehicule(Enum):
    """État courant d'un véhicule.

    Source unique de vérité pour la disponibilité : on ne stocke pas
    d'attribut `disponible` séparé, il est déduit du statut.
    """
    AU_DEPOT = "au_depot"       # disponible, prêt à recevoir une tournée
    EN_TOURNEE = "en_tournee"   # en cours de livraison
    EN_PAUSE = "en_pause"       # pause réglementaire du conducteur
    EN_PANNE = "en_panne"       # indisponible (scénario 2)


class TypeVehicule(Enum):
    """Gabarit du véhicule.

    Le gabarit conditionne la capacité, mais aussi les tronçons
    empruntables et les formalités : seul un ensemble routier équipé et
    autorisé passe la frontière.
    """
    FOURGON = "fourgon"                # jusqu'à ~3,5 t, distribution locale
    PORTEUR = "porteur"                # 3,5 à 19 t, liaisons régionales
    SEMI_REMORQUE = "semi_remorque"    # jusqu'à 24 t utiles, longue distance


@dataclass
class Vehicule:
    """Un véhicule de livraison.

    Structure de données passive : elle porte l'information et garantit
    sa propre cohérence, mais ne contient aucune logique métier.
    """

    # --- Identité ---
    id: str                     # ex. "V001", unique

    # --- Données métier ---
    capacite_kg: float          # charge utile maximale
    position_actuelle: str      # identifiant du noeud où se trouve le véhicule
    type_vehicule: TypeVehicule = TypeVehicule.PORTEUR
    pays_base: str = "MA"       # code ISO 3166-1 alpha-2 de rattachement
    autorise_international: bool = False    # licence de transport international

    # --- État courant ---
    charge_actuelle_kg: float = 0.0
    statut: StatutVehicule = StatutVehicule.AU_DEPOT
    # Temps de conduite déjà effectué dans la journée, en minutes.
    conduite_effectuee_min: float = 0.0

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
        if (
            len(self.pays_base) != 2
            or not self.pays_base.isalpha()
            or not self.pays_base.isupper()
        ):
            raise ValueError(
                f"Véhicule {self.id} : code pays invalide, attendu deux "
                f"lettres majuscules (reçu : '{self.pays_base}')"
            )
        if not 0 <= self.conduite_effectuee_min <= CONDUITE_JOURNALIERE_MAX_MIN:
            raise ValueError(
                f"Véhicule {self.id} : temps de conduite effectué hors bornes, "
                f"attendu entre 0 et {CONDUITE_JOURNALIERE_MAX_MIN} minutes "
                f"(reçu : {self.conduite_effectuee_min})"
            )
        # Un fourgon reste un véhicule de distribution : il ne part pas à
        # l'international dans le périmètre retenu.
        if self.autorise_international and self.type_vehicule is TypeVehicule.FOURGON:
            raise ValueError(
                f"Véhicule {self.id} : un fourgon ne peut pas être déclaré "
                f"autorisé à l'international"
            )

    @property
    def capacite_restante(self) -> float:
        """Charge supplémentaire acceptable, en kilogrammes."""
        return self.capacite_kg - self.charge_actuelle_kg

    @property
    def conduite_restante_min(self) -> float:
        """Temps de conduite encore autorisé aujourd'hui, en minutes."""
        return CONDUITE_JOURNALIERE_MAX_MIN - self.conduite_effectuee_min

    @property
    def disponible(self) -> bool:
        """Un véhicule est disponible s'il est au dépôt et peut encore rouler.

        La disponibilité n'est plus une simple question de statut : un
        véhicule au dépôt dont le conducteur a épuisé son temps de
        conduite ne peut pas repartir aujourd'hui.
        """
        return (
            self.statut is StatutVehicule.AU_DEPOT
            and self.conduite_restante_min > 0
        )