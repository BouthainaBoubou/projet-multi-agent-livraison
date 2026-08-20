"""Modèles décrivant le résultat d'une optimisation.

Structures passives : elles portent une décision déjà prise. Aucune
logique de calcul ici — elle appartient à l'`OptimizationAgent`.
"""

from dataclasses import dataclass, field


@dataclass
class Tournee:
    """La mission confiée à un véhicule.

    `arrets` ne contient que les points où le véhicule s'arrête, en
    commençant par son point de départ. L'itinéraire détaillé — tous les
    noeuds traversés — n'est pas stocké : il se redemande à la volée par
    `RouteAgent.itineraire_complet`, pour éviter deux versions d'une même
    vérité.
    """

    vehicule_id: str
    arrets: list[str]
    commandes: list[str] = field(default_factory=list)

    # --- Grandeurs calculées à la construction du plan ---
    distance_km: float = 0.0
    duree_min: float = 0.0          # temps écoulé, repos réglementaires inclus
    conduite_min: float = 0.0       # dont conduite effective
    jours: int = 1                  # journées de conduite mobilisées
    cout_dh: float = 0.0
    retard_pondere: float = 0.0
    charge_kg: float = 0.0
    # Somme, sur les commandes de la tournée, du nombre d'arrêts
    # intermédiaires subis avant leur livraison, pondéré par leur classe
    # de fragilité. Vaut zéro pour une tournée de marchandises standard.
    risque_fragilite: float = 0.0

    # Heure d'arrivée à chaque arrêt, en minutes depuis le départ.
    arrivees: dict[str, float] = field(default_factory=dict)

    @property
    def nb_commandes(self) -> int:
        return len(self.commandes)

    @property
    def est_vide(self) -> bool:
        """Un véhicule sans commande n'est pas une tournée, c'est un véhicule."""
        return not self.commandes


@dataclass
class Rejet:
    """Une commande qu'aucun véhicule n'a pu prendre, et pourquoi.

    Le motif est obligatoire. Une commande écartée sans explication est
    indéfendable : le dispatcheur doit pouvoir décider s'il affrète, s'il
    reporte, ou s'il négocie le délai.
    """

    commande_id: str
    motif: str


@dataclass
class Plan:
    """Le résultat complet d'une optimisation."""

    tournees: list[Tournee] = field(default_factory=list)
    rejets: list[Rejet] = field(default_factory=list)

    @property
    def vehicules_mobilises(self) -> int:
        return sum(1 for tournee in self.tournees if not tournee.est_vide)

    @property
    def distance_totale_km(self) -> float:
        return sum(tournee.distance_km for tournee in self.tournees)

    @property
    def cout_total_dh(self) -> float:
        return sum(tournee.cout_dh for tournee in self.tournees)

    @property
    def retard_total_pondere(self) -> float:
        return sum(tournee.retard_pondere for tournee in self.tournees)

    @property
    def risque_total(self) -> float:
        """Risque de casse cumulé sur l'ensemble des tournées."""
        return sum(tournee.risque_fragilite for tournee in self.tournees)

    @property
    def commandes_servies(self) -> int:
        return sum(tournee.nb_commandes for tournee in self.tournees)
