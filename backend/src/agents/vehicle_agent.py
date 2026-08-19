"""Agent responsable de la gestion des véhicules.

Il ne connaît que les véhicules : ni commandes, ni routes, ni graphe.
"""

from src.models.vehicule import StatutVehicule, Vehicule


class VehicleAgent:
    """Gère la flotte de véhicules du système.

    L'agent reçoit sa liste à la construction : il ne va jamais la
    chercher lui-même.
    """

    def __init__(self, vehicules: list[Vehicule]) -> None:
        self.vehicules = vehicules

    # --- Lectures ---

    def vehicules_disponibles(
        self, pour_international: bool = False
    ) -> list[Vehicule]:
        """Les véhicules prêts à partir en tournée.

        À l'échelle nationale et internationale, « disponible » ne suffit
        plus : une liaison transfrontalière exige en plus une licence de
        transport international. Le paramètre est explicite et vaut faux
        par défaut, pour que le cas courant reste le cas simple.
        """
        return [
            vehicule for vehicule in self.vehicules
            if vehicule.disponible
            and (vehicule.autorise_international or not pour_international)
        ]

    def capacite_disponible_totale(
        self, pour_international: bool = False
    ) -> float:
        """Somme des capacités restantes des véhicules mobilisables."""
        return sum(
            vehicule.capacite_restante
            for vehicule in self.vehicules_disponibles(pour_international)
        )

    def trouver_vehicule_par_id(self, id_vehicule: str) -> Vehicule | None:
        """Retourne le véhicule correspondant, ou None s'il n'existe pas.

        Une recherche infructueuse est une situation normale, pas un bug :
        elle retourne None au lieu de lever une exception.
        """
        for vehicule in self.vehicules:
            if vehicule.id == id_vehicule:
                return vehicule
        return None

    def peut_charger(self, id_vehicule: str, poids: float) -> bool:
        """Indique si ce véhicule peut accepter ce poids supplémentaire.

        Requête sans effet de bord : on peut l'appeler autant de fois
        qu'on veut, rien ne change dans le système.
        """
        vehicule = self._exiger_vehicule(id_vehicule)
        return vehicule.disponible and poids <= vehicule.capacite_restante

    def peut_tenir_la_route(self, id_vehicule: str, duree_min: float) -> bool:
        """Indique si le temps de conduite restant couvre cette durée.

        Contrainte propre à la longue distance : une tournée Casablanca -
        Agadir - retour dépasse la journée de conduite autorisée, quelle
        que soit la capacité du véhicule.
        """
        vehicule = self._exiger_vehicule(id_vehicule)
        return duree_min <= vehicule.conduite_restante_min

    # --- Modifications ---

    def charger(self, id_vehicule: str, poids: float) -> None:
        """Ajoute un poids à la charge actuelle d'un véhicule."""
        vehicule = self._exiger_vehicule(id_vehicule)
        if not self.peut_charger(id_vehicule, poids):
            raise ValueError(
                f"Véhicule {id_vehicule} : impossible de charger {poids} kg "
                f"(capacité restante : {vehicule.capacite_restante} kg, "
                f"statut : {vehicule.statut.value})"
            )
        vehicule.charge_actuelle_kg += poids

    def decharger(self, id_vehicule: str, poids: float) -> None:
        """Retire un poids livré de la charge actuelle d'un véhicule."""
        vehicule = self._exiger_vehicule(id_vehicule)
        if poids > vehicule.charge_actuelle_kg:
            raise ValueError(
                f"Véhicule {id_vehicule} : impossible de décharger {poids} kg, "
                f"il n'en transporte que {vehicule.charge_actuelle_kg}"
            )
        vehicule.charge_actuelle_kg -= poids

    def consommer_temps_conduite(
        self, id_vehicule: str, duree_min: float
    ) -> None:
        """Impute une durée de conduite au véhicule.

        Quand le quota journalier est épuisé, le véhicule passe en pause :
        on ne le laisse pas dans un état où il paraîtrait disponible.
        """
        vehicule = self._exiger_vehicule(id_vehicule)
        if duree_min < 0:
            raise ValueError(
                f"Véhicule {id_vehicule} : durée de conduite négative "
                f"(reçu : {duree_min})"
            )
        if not self.peut_tenir_la_route(id_vehicule, duree_min):
            raise ValueError(
                f"Véhicule {id_vehicule} : {duree_min} min de conduite "
                f"demandées, {vehicule.conduite_restante_min} min restantes "
                f"dans la journée réglementaire"
            )
        vehicule.conduite_effectuee_min += duree_min
        if vehicule.conduite_restante_min == 0:
            vehicule.statut = StatutVehicule.EN_PAUSE

    def reinitialiser_journee(self, id_vehicule: str) -> None:
        """Remet à zéro le compteur de conduite (repos journalier pris)."""
        vehicule = self._exiger_vehicule(id_vehicule)
        vehicule.conduite_effectuee_min = 0.0
        if vehicule.statut is StatutVehicule.EN_PAUSE:
            vehicule.statut = StatutVehicule.AU_DEPOT

    def remettre_en_service(self, id_vehicule: str) -> None:
        """Remet au dépôt un véhicule réparé.

        Symétrique de `signaler_panne`. Sans elle, un scénario d'incident
        ne peut pas être annulé : on ne pourrait mesurer que des
        dégradations cumulées, jamais l'effet d'un incident isolé.
        """
        vehicule = self._exiger_vehicule(id_vehicule)
        if vehicule.statut is not StatutVehicule.EN_PANNE:
            raise ValueError(
                f"Véhicule {id_vehicule} : statut {vehicule.statut.value}, "
                f"seul un véhicule en panne peut être remis en service"
            )
        vehicule.statut = StatutVehicule.AU_DEPOT

    def signaler_panne(self, id_vehicule: str) -> None:
        """Rend un véhicule indisponible (scénario 2 du cahier des charges).

        On modifie le statut, jamais `disponible` : cette propriété est
        calculée et suit automatiquement.
        """
        vehicule = self._exiger_vehicule(id_vehicule)
        vehicule.statut = StatutVehicule.EN_PANNE

    # --- Interne ---

    def _exiger_vehicule(self, id_vehicule: str) -> Vehicule:
        """Retrouve un véhicule, ou lève une exception s'il n'existe pas."""
        vehicule = self.trouver_vehicule_par_id(id_vehicule)
        if vehicule is None:
            raise ValueError(f"Véhicule inconnu : {id_vehicule}")
        return vehicule