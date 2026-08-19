"""Agent chef d'orchestre : il fait travailler les cinq autres.

Il ne calcule rien lui-même. Son rôle est d'enchaîner les appels dans le
bon ordre quand un événement survient, et de garder trace de ce qui a
été décidé et pourquoi. C'est le seul agent qui a le droit de connaître
tous les autres ; c'est aussi le seul point d'entrée de l'application.

La réoptimisation dynamique tient en trois gestes, toujours les mêmes :

1. enregistrer l'événement auprès de l'agent concerné (panne au
   `VehicleAgent`, blocage au `TrafficAgent`) ;
2. remettre le système dans un état replanifiable — les commandes non
   livrées reviennent dans le vivier ;
3. relancer l'optimisation et comparer le nouveau Z à l'ancien.

Le troisième geste est celui qui compte pour la soutenance : sans
comparaison chiffrée avant/après, « le système réagit » n'est qu'une
affirmation.
"""

from dataclasses import dataclass, field

from src.agents.optimization_agent import OptimizationAgent
from src.agents.order_agent import OrderAgent
from src.agents.route_agent import RouteAgent
from src.agents.traffic_agent import TrafficAgent
from src.agents.vehicle_agent import VehicleAgent
from src.data.loader import DonneesLivraison
from src.models.commande import StatutCommande
from src.models.tournee import Plan, Tournee
from src.models.vehicule import StatutVehicule


@dataclass
class Evenement:
    """Une ligne du journal des décisions.

    Le numéro remplace un horodatage : il rend le journal reproductible
    d'une exécution à l'autre, ce qu'une heure réelle interdirait. Deux
    exécutions du même scénario doivent produire le même journal, sinon
    aucun test ne peut le vérifier.
    """

    numero: int
    type: str
    description: str
    z_avant: float | None = None
    z_apres: float | None = None

    @property
    def variation(self) -> float | None:
        """Écart de la fonction objectif provoqué par l'événement."""
        if self.z_avant is None or self.z_apres is None:
            return None
        return round(self.z_apres - self.z_avant, 1)


@dataclass
class CoordinatorAgent:
    """Orchestre les agents et tient le journal des décisions."""

    donnees: DonneesLivraison
    order: OrderAgent = field(init=False)
    vehicle: VehicleAgent = field(init=False)
    traffic: TrafficAgent = field(init=False)
    route: RouteAgent = field(init=False)
    optimisation: OptimizationAgent = field(init=False)
    plan: Plan | None = field(init=False, default=None)
    journal: list[Evenement] = field(init=False, default_factory=list)

    def __post_init__(self) -> None:
        self.order = OrderAgent(self.donnees.commandes)
        self.vehicle = VehicleAgent(self.donnees.vehicules)
        self.traffic = TrafficAgent(self.donnees.troncons)
        self.route = RouteAgent(self.donnees.noeuds, self.donnees.troncons)
        self.optimisation = OptimizationAgent(self.order, self.vehicle, self.route)

    # --- Planification ---

    def planifier(self, motif: str = "planification initiale") -> Plan:
        """Calcule un plan de tournées et l'inscrit au journal."""
        z_avant = self.score()["Z"] if self.plan else None
        self._liberer()
        self.plan = self.optimisation.optimiser()
        self._inscrire(
            "planification", motif, z_avant, self.score()["Z"]
        )
        return self.plan

    def score(self) -> dict[str, float]:
        """Note du plan courant."""
        if self.plan is None:
            raise ValueError("Aucun plan : appeler planifier() d'abord")
        return self.optimisation.evaluer(self.plan)

    def itineraire(self, tournee: Tournee) -> list[str]:
        """Itinéraire détaillé d'une tournée, pour la carte du chauffeur."""
        return self.route.itineraire_complet(tournee.arrets)

    # --- Événements ---

    def declarer_panne(self, id_vehicule: str) -> Plan:
        """Scénario 2 : un véhicule tombe en panne, ses commandes repartent.

        Le véhicule cesse d'être disponible, donc l'optimiseur ne le
        proposera plus. Ses commandes, elles, ne sont pas perdues : la
        libération générale les remet dans le vivier avant le nouveau
        calcul.
        """
        self.vehicle.signaler_panne(id_vehicule)
        return self._reagir("panne", f"véhicule {id_vehicule} immobilisé")

    def declarer_reparation(self, id_vehicule: str) -> Plan:
        """Le véhicule est réparé et redevient mobilisable."""
        self.vehicle.remettre_en_service(id_vehicule)
        return self._reagir("réparation", f"véhicule {id_vehicule} réparé")

    def declarer_deblocage(self, origine: str, destination: str) -> Plan:
        """La liaison est rouverte."""
        self.traffic.debloquer_troncon(origine, destination)
        self.route.rafraichir()
        return self._reagir(
            "déblocage", f"liaison {origine} – {destination} rouverte"
        )

    def declarer_blocage(self, origine: str, destination: str) -> Plan:
        """Scénario 3 : une liaison devient impraticable.

        L'ordre des deux premières lignes est essentiel : bloquer le
        tronçon ne suffit pas, il faut reconstruire le graphe. Sans
        `rafraichir`, l'optimiseur continuerait de planifier des trajets
        par la route barrée.
        """
        self.traffic.bloquer_troncon(origine, destination)
        self.route.rafraichir()
        return self._reagir("blocage", f"liaison {origine} – {destination} coupée")

    def declarer_congestion(
        self, origine: str, destination: str, niveau: float
    ) -> Plan:
        """Scénario 1 : le trafic se dégrade sur un axe."""
        self.traffic.mettre_a_jour_trafic(origine, destination, niveau)
        self.route.rafraichir()
        return self._reagir(
            "congestion", f"trafic × {niveau} sur {origine} – {destination}"
        )

    def declarer_attente_frontiere(
        self, origine: str, destination: str, duree_min: float
    ) -> Plan:
        """Scénario 4 : la file s'allonge au port ou à la douane."""
        self.traffic.mettre_a_jour_attente_frontiere(origine, destination, duree_min)
        self.route.rafraichir()
        return self._reagir(
            "attente",
            f"{duree_min:.0f} min d'attente sur {origine} – {destination}",
        )

    def declarer_livraison(self, id_commande: str) -> None:
        """Une commande est livrée : elle sort définitivement du vivier.

        Aucune replanification : livrer était prévu. Seul l'imprévu
        déclenche un nouveau calcul.
        """
        self.order.marquer_livree(id_commande)
        self._inscrire("livraison", f"commande {id_commande} livrée")

    # --- Interne ---

    def _reagir(self, type_evenement: str, description: str) -> Plan:
        """Enregistre un incident, replanifie, et mesure l'écart de Z."""
        z_avant = self.score()["Z"] if self.plan else None
        self._liberer()
        self.plan = self.optimisation.optimiser()
        self._inscrire(type_evenement, description, z_avant, self.score()["Z"])
        return self.plan

    def _liberer(self) -> None:
        """Remet le système dans un état replanifiable.

        Toute commande non livrée redevient disponible et tout véhicule
        encore valide repart à vide. On replanifie donc l'intégralité du
        reste à faire, plutôt que de rafistoler le plan existant :
        c'est plus simple à écrire, plus simple à défendre, et la taille
        du problème le permet largement.
        """
        for commande in self.donnees.commandes:
            if commande.statut in (StatutCommande.EN_ATTENTE, StatutCommande.LIVREE):
                continue
            self.order.remettre_en_attente(commande.id)

        for vehicule in self.donnees.vehicules:
            if vehicule.statut is StatutVehicule.EN_PANNE:
                continue
            if vehicule.charge_actuelle_kg > 0:
                self.vehicle.decharger(vehicule.id, vehicule.charge_actuelle_kg)

    def _inscrire(
        self,
        type_evenement: str,
        description: str,
        z_avant: float | None = None,
        z_apres: float | None = None,
    ) -> None:
        self.journal.append(
            Evenement(
                numero=len(self.journal) + 1,
                type=type_evenement,
                description=description,
                z_avant=z_avant,
                z_apres=z_apres,
            )
        )

    # --- Restitution ---

    def resume(self) -> str:
        """Vue texte du plan courant, pour la console et les tests."""
        if self.plan is None:
            return "Aucun plan."

        note = self.score()
        lignes = [
            f"Z = {note['Z']}  "
            f"({note['distance_km']} km · {note['vehicules']} véhicules · "
            f"retard pondéré {note['retard_pondere']} · {note['rejets']} rejet(s))",
            "",
        ]
        for tournee in sorted(self.plan.tournees, key=lambda t: t.vehicule_id):
            lignes.append(
                f"{tournee.vehicule_id} : {' → '.join(tournee.arrets)}  "
                f"[{tournee.nb_commandes} cmd · {tournee.charge_kg:.0f} kg · "
                f"{tournee.distance_km:.0f} km · {tournee.jours} j · "
                f"retard {tournee.retard_pondere:.0f}]"
            )
        for rejet in self.plan.rejets:
            lignes.append(f"REJET {rejet.commande_id} : {rejet.motif}")
        return "\n".join(lignes)

    def journal_texte(self) -> str:
        """Vue texte du journal des décisions."""
        lignes = []
        for evenement in self.journal:
            variation = evenement.variation
            suffixe = "" if variation is None else f"   ΔZ = {variation:+.1f}"
            lignes.append(
                f"{evenement.numero:>2}. [{evenement.type}] "
                f"{evenement.description}{suffixe}"
            )
        return "\n".join(lignes)