"""Modèle représentant un tronçon du réseau de transport.

le trafic n'est plus une valeur figée que l'on
déclare à la main. Chaque tronçon porte désormais un **profil**, et à
chaque profil correspond une courbe de congestion selon l'heure. Un plan
calculé pour un départ à 6 h et un plan calculé pour un départ à 8 h ne
sont plus identiques — ce qu'ils n'auraient jamais dû être.
"""

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


class ProfilTrafic(Enum):
    """Comportement d'un tronçon face aux heures de pointe.

    Ce n'est pas le niveau de trafic, c'est la **façon dont il varie**.
    Une autoroute de rase campagne et une entrée d'agglomération ne
    réagissent pas de la même manière au même moment de la journée.
    """
    AUTOROUTE = "autoroute"          # voie rapide interurbaine, peu sensible
    NATIONALE = "nationale"          # route ordinaire, sensible aux pointes
    ACCES_URBAIN = "acces_urbain"    # entrée d'agglomération ou approche portuaire
    MARITIME = "maritime"            # traversée : aucune congestion routière


# Tranches horaires, en heures pleines. Bornes [debut, fin[.
TRANCHES_HORAIRES: tuple[tuple[int, int, str], ...] = (
    (0, 6, "nuit"),
    (6, 9, "pointe_matin"),
    (9, 16, "creux_jour"),
    (16, 20, "pointe_soir"),
    (20, 24, "soiree"),
)

# Multiplicateur du temps de roulage, par profil et par tranche horaire.
# Ces coefficients sont **typés et assumés**, non mesurés : le projet ne
# dispose d'aucune source de trafic en temps réel. Ils reproduisent la
# forme connue d'une journée de circulation (deux pointes, un creux de
# nuit) et servent à démontrer que le système en tient compte. Les
# remplacer par des mesures réelles ne demanderait de toucher qu'à cette
# table.
COEFFICIENTS_HORAIRES: dict[ProfilTrafic, dict[str, float]] = {
    ProfilTrafic.AUTOROUTE: {
        "nuit": 1.0, "pointe_matin": 1.15, "creux_jour": 1.05,
        "pointe_soir": 1.20, "soiree": 1.0,
    },
    ProfilTrafic.NATIONALE: {
        "nuit": 1.0, "pointe_matin": 1.25, "creux_jour": 1.10,
        "pointe_soir": 1.30, "soiree": 1.05,
    },
    ProfilTrafic.ACCES_URBAIN: {
        "nuit": 1.05, "pointe_matin": 1.60, "creux_jour": 1.25,
        "pointe_soir": 1.70, "soiree": 1.15,
    },
    ProfilTrafic.MARITIME: {
        "nuit": 1.0, "pointe_matin": 1.0, "creux_jour": 1.0,
        "pointe_soir": 1.0, "soiree": 1.0,
    },
}


def tranche_horaire(heure: int) -> str:
    """Nom de la tranche à laquelle appartient une heure de départ."""
    if not 0 <= heure <= 23:
        raise ValueError(
            f"Heure de départ invalide : {heure} (attendu entre 0 et 23)"
        )
    for debut, fin, nom in TRANCHES_HORAIRES:
        if debut <= heure < fin:
            return nom
    raise ValueError(f"Heure de départ non couverte par les tranches : {heure}")


def coefficient_horaire(profil: ProfilTrafic, heure: int) -> float:
    """Multiplicateur de congestion d'un profil à une heure donnée."""
    return COEFFICIENTS_HORAIRES[profil][tranche_horaire(heure)]


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
    # Sensibilité du tronçon aux heures de pointe. Donnée de référence :
    # elle ne change pas en cours de journée, contrairement au niveau de
    # trafic qu'elle sert à calculer.
    profil_trafic: ProfilTrafic = ProfilTrafic.NATIONALE

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
        # Le profil et le mode disent la même chose sous deux angles : les
        # laisser diverger produirait une traversée qui se congestionne.
        if self.mode is ModeTransport.MARITIME and self.profil_trafic is not ProfilTrafic.MARITIME:
            raise ValueError(
                f"Tronçon {self.origine} -> {self.destination} : tronçon "
                f"maritime, son profil de trafic doit être 'maritime' "
                f"(reçu : '{self.profil_trafic.value}')"
            )
        if self.mode is ModeTransport.ROUTIER and self.profil_trafic is ProfilTrafic.MARITIME:
            raise ValueError(
                f"Tronçon {self.origine} -> {self.destination} : tronçon "
                f"routier, son profil de trafic ne peut pas être 'maritime'"
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

    def trafic_a(self, heure: int) -> float:
        """Niveau de trafic que ce tronçon connaîtrait à cette heure.

        Requête sans effet de bord : elle ne modifie pas l'état courant.
        C'est le `TrafficAgent` qui décide de l'appliquer.
        """
        return coefficient_horaire(self.profil_trafic, heure)
