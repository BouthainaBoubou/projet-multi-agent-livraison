"""Agent responsable de la construction et de l'évaluation des tournées.

Il ne lit ni fichier ni graphe : il interroge les autres agents. Il
demande les commandes à `OrderAgent`, les véhicules à `VehicleAgent`,
les temps de trajet à `RouteAgent`, et compose. C'est le seul agent qui
croise plusieurs domaines, et c'est assumé : c'est son métier.

L'heuristique est **gloutonne par insertion** : les commandes sont
traitées de la plus urgente à la moins urgente, et chacune est confiée
au véhicule dont la tournée s'allonge le moins. Ce n'est pas optimal —
un solveur fera mieux — mais c'est complet, rapide, explicable, et cela
donne la **référence** à laquelle comparer toute méthode ultérieure.

Deux règles de modélisation à connaître avant de lire le code :

1. **Pas de retour au dépôt.** La tournée s'achève à la dernière
   livraison. À l'échelle nationale, imposer le retour rendrait presque
   toute mission infaisable dans la journée réglementaire.
2. **Les missions longues durent plusieurs jours.** Casablanca - Madrid
   demande plus de 9 h de conduite : la limite journalière ne rend pas
   la mission impossible, elle impose un repos de 11 h. Le temps écoulé
   à l'arrivée en tient compte, et c'est lui qu'on compare au délai.
"""

from dataclasses import dataclass, field
from math import ceil

from src.agents.order_agent import OrderAgent
from src.agents.route_agent import CheminIntrouvable, RouteAgent
from src.agents.vehicle_agent import VehicleAgent
from src.models.commande import Commande, TypeLivraison
from src.models.tournee import Plan, Rejet, Tournee
from src.models.vehicule import CONDUITE_JOURNALIERE_MAX_MIN, Vehicule

# Repos journalier obligatoire entre deux journées de conduite (11 h).
REPOS_JOURNALIER_MIN = 660.0

# Au-delà, la mission sort du périmètre du système : elle relève de
# l'affrètement ou d'un relais de conducteur, pas de l'optimisation.
JOURS_MAX_MISSION = 5


@dataclass
class Profil:
    """Le déroulé chiffré d'une suite d'arrêts, pour un véhicule donné."""

    duree_min: float = 0.0
    conduite_min: float = 0.0
    distance_km: float = 0.0
    cout_dh: float = 0.0
    jours: int = 1
    arrivees: dict[str, float] = field(default_factory=dict)


@dataclass
class _Chantier:
    """Tournée en cours de construction pour un véhicule."""

    vehicule: Vehicule
    arrets: list[str]
    commandes: list[Commande] = field(default_factory=list)
    charge_kg: float = 0.0
    profil: Profil = field(default_factory=Profil)


class OptimizationAgent:
    """Construit les tournées et sait noter une solution."""

    def __init__(
        self,
        order: OrderAgent,
        vehicle: VehicleAgent,
        route: RouteAgent,
        alpha: float = 1.0,
        beta: float = 500.0,
        gamma: float = 2.0,
        delta: float = 5000.0,
    ) -> None:
        self.order = order
        self.vehicle = vehicle
        self.route = route
        # Pondérations de la fonction objectif, réglables sans toucher au code.
        self.alpha = alpha      # le kilomètre
        self.beta = beta        # le véhicule mobilisé
        self.gamma = gamma      # la minute de retard, pondérée par la priorité
        self.delta = delta      # la commande non servie

    # --- Optimisation ---

    def optimiser(self) -> Plan:
        """Construit un plan de tournées pour toutes les commandes en attente.

        Les deux sous-problèmes sont traités dans l'ordre : d'abord
        l'international, ensuite le national. L'ordre n'est pas neutre —
        seuls trois véhicules peuvent franchir la frontière, alors que
        tous peuvent rouler au Maroc. Servir le national d'abord
        risquerait d'engager les semi-remorques sur Agadir et de laisser
        les commandes d'export sans véhicule.
        """
        chantiers = {
            vehicule.id: _Chantier(vehicule, [vehicule.position_actuelle])
            for vehicule in self.vehicle.vehicules_disponibles()
        }
        plan = Plan()

        for type_livraison in (TypeLivraison.INTERNATIONALE, TypeLivraison.NATIONALE):
            for commande in self.order.commandes_par_urgence(type_livraison):
                self._placer(commande, chantiers, plan)

        for chantier in chantiers.values():
            if chantier.commandes:
                plan.tournees.append(self._figer(chantier))

        self._appliquer(plan)
        return plan

    def _placer(
        self, commande: Commande, chantiers: dict[str, _Chantier], plan: Plan
    ) -> None:
        """Confie une commande au véhicule dont la tournée s'allonge le moins."""
        meilleur: tuple[float, _Chantier, list[str], Profil] | None = None
        obstacles: list[str] = []

        for chantier in chantiers.values():
            refus = self._refus(commande, chantier)
            if refus:
                obstacles.append(refus)
                continue

            candidates = 0
            for arrets, profil in self._insertions(commande, chantier):
                candidates += 1
                if profil.jours > JOURS_MAX_MISSION:
                    obstacles.append("mission trop longue")
                    continue
                surcout = profil.duree_min - chantier.profil.duree_min
                if meilleur is None or surcout < meilleur[0]:
                    meilleur = (surcout, chantier, arrets, profil)

            # Aucune insertion possible alors que le véhicule était
            # éligible : c'est que la destination n'est plus reliée au
            # réseau. Sans cette trace, le rejet serait expliqué par le
            # motif d'un autre véhicule — et le dispatcheur chercherait
            # un camion là où il faut rouvrir une route.
            if candidates == 0:
                obstacles.append(
                    f"destination {commande.destination} inaccessible "
                    f"depuis {chantier.arrets[0]}"
                )

        if meilleur is None:
            plan.rejets.append(Rejet(commande.id, self._motif(obstacles)))
            return

        _, chantier, arrets, profil = meilleur
        chantier.arrets = arrets
        chantier.profil = profil
        chantier.commandes.append(commande)
        chantier.charge_kg += commande.poids

    def _refus(self, commande: Commande, chantier: _Chantier) -> str | None:
        """Raison pour laquelle ce véhicule ne peut pas prendre cette commande.

        Retourne `None` s'il le peut. Les trois contraintes sont dures :
        aucune pénalité ne permet de les contourner.
        """
        vehicule = chantier.vehicule
        if chantier.arrets[0] != commande.origine:
            return f"aucun véhicule au point d'enlèvement {commande.origine}"
        if commande.est_internationale and not vehicule.autorise_international:
            return "aucun véhicule autorisé à l'international n'est disponible"
        if chantier.charge_kg + commande.poids > vehicule.capacite_kg:
            return "capacité insuffisante sur tous les véhicules éligibles"
        return None

    def _insertions(self, commande: Commande, chantier: _Chantier):
        """Énumère les tournées possibles après ajout de cette commande.

        Si la destination est déjà desservie, il n'y a rien à insérer :
        la commande rejoint un arrêt existant sans allonger la tournée.
        C'est le regroupement, et il vient gratuitement.
        """
        if commande.destination in chantier.arrets:
            yield list(chantier.arrets), chantier.profil
            return

        for position in range(1, len(chantier.arrets) + 1):
            arrets = (
                chantier.arrets[:position]
                + [commande.destination]
                + chantier.arrets[position:]
            )
            try:
                yield arrets, self._profiler(chantier.vehicule, arrets)
            except CheminIntrouvable:
                continue

    @staticmethod
    def _motif(obstacles: list[str]) -> str:
        """Choisit l'explication la plus informative parmi celles rencontrées.

        L'ordre reflète la précision du diagnostic, pas la gravité. Un
        obstacle de capacité prouve qu'un véhicule *éligible* existait —
        c'est donc plus informatif que « aucun véhicule autorisé », qui
        peut n'être remonté que par des véhicules hors sujet.
        """
        for cle in (
            "inaccessible", "capacité", "trop longue",
            "autorisé à l'international", "enlèvement",
        ):
            for obstacle in obstacles:
                if cle in obstacle:
                    return obstacle
        return "aucun véhicule disponible"

    # --- Chiffrage ---

    def _profiler(self, vehicule: Vehicule, arrets: list[str]) -> Profil:
        """Déroule une suite d'arrêts et en calcule les grandeurs.

        Le repos réglementaire n'est pas une pause au milieu d'une étape :
        on le place à la fin de chaque journée de conduite entamée. C'est
        une simplification — un vrai conducteur s'arrête où il peut — mais
        elle ne change pas l'ordre de grandeur de l'heure d'arrivée.
        """
        profil = Profil()
        disponible_aujourdhui = vehicule.conduite_restante_min

        for depart, arrivee in zip(arrets, arrets[1:]):
            profil.duree_min += self.route.temps_trajet(depart, arrivee)
            profil.conduite_min += self.route.temps_conduite(depart, arrivee)
            profil.distance_km += self.route.distance_trajet(depart, arrivee)
            profil.cout_dh += self.route.cout_trajet(depart, arrivee)

            jours = self._jours(profil.conduite_min, disponible_aujourdhui)
            profil.arrivees[arrivee] = (
                profil.duree_min + (jours - 1) * REPOS_JOURNALIER_MIN
            )

        profil.jours = self._jours(profil.conduite_min, disponible_aujourdhui)
        profil.duree_min += (profil.jours - 1) * REPOS_JOURNALIER_MIN
        return profil

    @staticmethod
    def _jours(conduite_min: float, disponible_aujourdhui: float) -> int:
        """Nombre de journées de conduite qu'exige une durée de conduite.

        La première journée est souvent entamée : on ne dispose que du
        solde du conducteur, pas des 9 h pleines.
        """
        if conduite_min <= disponible_aujourdhui:
            return 1
        reste = conduite_min - disponible_aujourdhui
        return 1 + ceil(reste / CONDUITE_JOURNALIERE_MAX_MIN)

    def _figer(self, chantier: _Chantier) -> Tournee:
        """Transforme une tournée en construction en résultat immuable."""
        retard = sum(
            max(0.0, chantier.profil.arrivees[commande.destination]
                - commande.delai_minutes) * commande.priorite.value
            for commande in chantier.commandes
        )
        return Tournee(
            vehicule_id=chantier.vehicule.id,
            arrets=list(chantier.arrets),
            commandes=[commande.id for commande in chantier.commandes],
            distance_km=round(chantier.profil.distance_km, 1),
            duree_min=round(chantier.profil.duree_min),
            conduite_min=round(chantier.profil.conduite_min),
            jours=chantier.profil.jours,
            cout_dh=round(chantier.profil.cout_dh),
            retard_pondere=round(retard, 1),
            charge_kg=chantier.charge_kg,
            arrivees={
                noeud: round(minute)
                for noeud, minute in chantier.profil.arrivees.items()
            },
        )

    def _appliquer(self, plan: Plan) -> None:
        """Inscrit les décisions dans l'état des agents.

        Le compteur de conduite des véhicules n'est **pas** consommé : un
        plan est une projection, pas une exécution. C'est le
        `CoordinatorAgent` qui fera avancer le temps le jour où le
        système simulera le déroulé réel.
        """
        for tournee in plan.tournees:
            for id_commande in tournee.commandes:
                self.order.assigner_commande(id_commande, tournee.vehicule_id)
            self.vehicle.charger(tournee.vehicule_id, tournee.charge_kg)

    # --- Évaluation ---

    def evaluer(self, plan: Plan) -> dict[str, float]:
        """Note un plan : Z et le détail de ses quatre termes.

        Z = α × distance + β × véhicules + γ × retards pondérés
            + δ × commandes non servies

        Le quatrième terme n'est pas décoratif. Sans lui, la meilleure
        solution serait de tout refuser : zéro kilomètre, zéro véhicule,
        zéro retard, Z = 0. Le rejet doit coûter plus cher que le pire
        service possible.

        Fonction pure : elle ne modifie rien, elle peut donc noter avec
        le même juge une solution gloutonne et une solution issue d'un
        solveur. C'est la condition pour que la comparaison ait un sens.
        """
        distance = plan.distance_totale_km
        vehicules = plan.vehicules_mobilises
        retard = plan.retard_total_pondere
        rejets = len(plan.rejets)

        return {
            "Z": round(
                self.alpha * distance
                + self.beta * vehicules
                + self.gamma * retard
                + self.delta * rejets,
                1,
            ),
            "distance_km": round(distance, 1),
            "vehicules": vehicules,
            "retard_pondere": round(retard, 1),
            "rejets": rejets,
            "commandes_servies": plan.commandes_servies,
            "cout_dh": round(plan.cout_total_dh),
        }