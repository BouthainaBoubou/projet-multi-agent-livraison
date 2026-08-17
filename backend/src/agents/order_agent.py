"""Agent responsable de la gestion des commandes.

Il ne connaît que les commandes : ni véhicules, ni routes, ni graphe.
Toute question croisant deux domaines appartient à l'agent qui orchestre.
"""

from src.models.commande import Commande, StatutCommande


class OrderAgent:
    """Gère l'ensemble des commandes du système.

    L'agent reçoit sa liste à la construction : il ne va jamais la
    chercher lui-même. C'est ce qui le rend testable sans base de
    données et indépendant de la source des données.
    """

    def __init__(self, commandes: list[Commande]) -> None:
        self.commandes = commandes

    # --- Lectures ---

    def commandes_en_attente(self) -> list[Commande]:
        """Les commandes pas encore affectées à un véhicule."""
        return [
            commande for commande in self.commandes
            if commande.statut == StatutCommande.EN_ATTENTE
        ]

    def commandes_par_urgence(self) -> list[Commande]:
        """Les commandes en attente, de la plus urgente à la moins urgente.

        Tri sur deux critères de sens opposés : priorité décroissante
        (d'où le signe moins), puis délai croissant à priorité égale.
        """
        return sorted(
            self.commandes_en_attente(),
            key=lambda commande: (
                -commande.priorite.value,
                commande.delai_minutes,
            ),
        )

    def trouver_commande_par_id(self, id_commande: str) -> Commande | None:
        """Retourne la commande correspondante, ou None si elle n'existe pas.

        Une recherche infructueuse est une situation normale, pas un bug :
        elle retourne None au lieu de lever une exception.
        """
        for commande in self.commandes:
            if commande.id == id_commande:
                return commande
        return None

    # --- Modifications ---

    def assigner_commande(self, id_commande: str, vehicule_id: str) -> None:
        """Enregistre qu'une commande part avec un véhicule donné.

        Les deux échecs possibles sont des bugs de l'appelant, pas des
        cas normaux : ils lèvent une exception plutôt que de retourner
        un booléen que rien n'obligerait à vérifier.
        """
        commande = self.trouver_commande_par_id(id_commande)
        if commande is None:
            raise ValueError(f"Commande inconnue : {id_commande}")
        if commande.statut != StatutCommande.EN_ATTENTE:
            raise ValueError(
                f"Commande {id_commande} : statut {commande.statut.value}, "
                f"seule une commande en attente peut être assignée"
            )
        commande.vehicule_assigne = vehicule_id
        commande.statut = StatutCommande.ASSIGNEE