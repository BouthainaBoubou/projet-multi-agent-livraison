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

    def vehicules_disponibles(self) -> list[Vehicule]:
        """Les véhicules prêts à partir en tournée."""
        return [
            vehicule for vehicule in self.vehicules
            if vehicule.disponible
        ]

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
        vehicule = self.trouver_vehicule_par_id(id_vehicule)
        if vehicule is None:
            raise ValueError(f"Véhicule inconnu : {id_vehicule}")
        return vehicule.disponible and poids <= vehicule.capacite_restante

    # --- Modifications ---

    def charger(self, id_vehicule: str, poids: float) -> None:
        """Ajoute un poids à la charge actuelle d'un véhicule."""
        vehicule = self.trouver_vehicule_par_id(id_vehicule)
        if vehicule is None:
            raise ValueError(f"Véhicule inconnu : {id_vehicule}")
        if not self.peut_charger(id_vehicule, poids):
            raise ValueError(
                f"Véhicule {id_vehicule} : impossible de charger {poids} kg "
                f"(capacité restante : {vehicule.capacite_restante} kg, "
                f"statut : {vehicule.statut.value})"
            )
        vehicule.charge_actuelle_kg += poids

    def signaler_panne(self, id_vehicule: str) -> None:
        """Rend un véhicule indisponible (scénario 2 du cahier des charges).

        On modifie le statut, jamais `disponible` : cette propriété est
        calculée et suit automatiquement.
        """
        vehicule = self.trouver_vehicule_par_id(id_vehicule)
        if vehicule is None:
            raise ValueError(f"Véhicule inconnu : {id_vehicule}")
        vehicule.statut = StatutVehicule.EN_PANNE