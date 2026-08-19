"""Agent responsable de la gestion des commandes.

Il ne connaît que les commandes : ni véhicules, ni routes, ni graphe.
Toute question croisant deux domaines appartient à l'agent qui orchestre.
"""

from src.models.commande import Commande, StatutCommande, TypeLivraison


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
            if commande.statut is StatutCommande.EN_ATTENTE
        ]

    def commandes_par_type(self, type_livraison: TypeLivraison) -> list[Commande]:
        """Les commandes en attente d'une portée géographique donnée.

        Le périmètre couvre deux problèmes de nature différente : la
        distribution nationale et les liaisons internationales, qui
        n'admettent pas les mêmes véhicules. L'agent sait les séparer
        sans rien connaître des noeuds : le type a été calculé une fois
        pour toutes au chargement.
        """
        return [
            commande for commande in self.commandes_en_attente()
            if commande.type_livraison is type_livraison
        ]

    def commandes_par_urgence(
        self, type_livraison: TypeLivraison | None = None
    ) -> list[Commande]:
        """Les commandes en attente, de la plus urgente à la moins urgente.

        Tri sur deux critères de sens opposés : priorité décroissante
        (d'où le signe moins), puis délai croissant à priorité égale.
        Le filtre par type est optionnel : sans argument, on trie tout.
        """
        commandes = (
            self.commandes_en_attente()
            if type_livraison is None
            else self.commandes_par_type(type_livraison)
        )
        return sorted(
            commandes,
            key=lambda commande: (
                -commande.priorite.value,
                commande.delai_minutes,
            ),
        )

    def poids_total_en_attente(
        self, type_livraison: TypeLivraison | None = None
    ) -> float:
        """Somme des poids restant à charger, en kilogrammes.

        Sert au dimensionnement : comparée à la capacité disponible de la
        flotte, elle dit immédiatement si le scénario est faisable.
        """
        commandes = (
            self.commandes_en_attente()
            if type_livraison is None
            else self.commandes_par_type(type_livraison)
        )
        return sum(commande.poids for commande in commandes)

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
        commande = self._exiger_commande(id_commande)
        if commande.statut is not StatutCommande.EN_ATTENTE:
            raise ValueError(
                f"Commande {id_commande} : statut {commande.statut.value}, "
                f"seule une commande en attente peut être assignée"
            )
        commande.vehicule_assigne = vehicule_id
        commande.statut = StatutCommande.ASSIGNEE

    def marquer_livree(self, id_commande: str) -> None:
        """Clôt une commande arrivée à destination."""
        commande = self._exiger_commande(id_commande)
        if commande.statut not in (
            StatutCommande.ASSIGNEE, StatutCommande.EN_COURS
        ):
            raise ValueError(
                f"Commande {id_commande} : statut {commande.statut.value}, "
                f"seule une commande assignée ou en cours peut être livrée"
            )
        commande.statut = StatutCommande.LIVREE

    def marquer_echouee(self, id_commande: str) -> None:
        """Déclare une commande impossible à livrer.

        Elle est détachée de son véhicule : laisser le lien donnerait à
        croire qu'une tournée la transporte encore.
        """
        commande = self._exiger_commande(id_commande)
        commande.statut = StatutCommande.ECHOUEE
        commande.vehicule_assigne = None

    def remettre_en_attente(self, id_commande: str) -> None:
        """Détache une commande de son véhicule pour la réaffecter.

        C'est l'opération centrale de la réoptimisation dynamique : à la
        panne d'un véhicule, ses commandes reviennent dans le vivier au
        lieu d'être perdues.
        """
        commande = self._exiger_commande(id_commande)
        if commande.statut is StatutCommande.LIVREE:
            raise ValueError(
                f"Commande {id_commande} : déjà livrée, elle ne peut pas "
                f"revenir en attente"
            )
        commande.statut = StatutCommande.EN_ATTENTE
        commande.vehicule_assigne = None

    # --- Interne ---

    def _exiger_commande(self, id_commande: str) -> Commande:
        """Retrouve une commande, ou lève une exception si elle n'existe pas."""
        commande = self.trouver_commande_par_id(id_commande)
        if commande is None:
            raise ValueError(f"Commande inconnue : {id_commande}")
        return commande