"""Agent responsable de la gestion des commandes.

Il ne connaît que les commandes : ni véhicules, ni routes, ni graphe.
Toute question croisant deux domaines appartient à l'agent qui orchestre.

l'agent porte aussi la **saisie** : une commande
dont un critère de classification manque au fichier est bloquée au
statut `INCOMPLETE`, et c'est le dispatcheur qui la débloque en la
complétant. Le programme ne choisit jamais à sa place.
"""

from src.models.commande import (
    Commande, StatutCommande, TypeLivraison, convertir_critere,
    valeurs_possibles,
)

# États dans lesquels une commande peut encore être reclassée. Une fois
# le véhicule parti, changer la fragilité ou le niveau de service d'un
# lot déjà chargé ne veut plus rien dire : la marchandise est dans le
# camion, telle qu'elle a été chargée.
STATUTS_MODIFIABLES = (
    StatutCommande.INCOMPLETE,
    StatutCommande.EN_ATTENTE,
    StatutCommande.ASSIGNEE,
)


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
        """Les commandes complètes, pas encore affectées à un véhicule.

        Une commande incomplète n'y figure pas : elle n'a pas de statut
        `EN_ATTENTE`. C'est par ce seul filtre que le blocage se propage
        à toute la chaîne — l'optimiseur n'a rien de particulier à
        vérifier, il ne voit tout simplement pas les commandes non
        classées.
        """
        return [
            commande for commande in self.commandes
            if commande.statut is StatutCommande.EN_ATTENTE
        ]

    def commandes_incompletes(self) -> list[Commande]:
        """Les commandes à compléter avant toute planification.

        C'est la liste de travail du dispatcheur : chacune sait dire
        elle-même ce qui lui manque, via `criteres_manquants`.
        """
        return [
            commande for commande in self.commandes
            if commande.statut is StatutCommande.INCOMPLETE
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
        La priorité n'est plus lue dans un fichier : elle est calculée
        par la grille de classification, donc explicable ligne à ligne.
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

    def commandes_sensibles(self) -> list[Commande]:
        """Les commandes à diffusion restreinte, tous statuts confondus."""
        return [
            commande for commande in self.commandes
            if commande.confidentialite is not None and commande.est_sensible
        ]

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

    def vue(self, id_commande: str, role: str) -> dict:
        """Ce qu'un rôle a le droit de voir d'une commande."""
        return self._exiger_commande(id_commande).vue(role)

    # --- Saisie des critères de classification ---

    def completer_commande(self, id_commande: str, **criteres) -> Commande:
        """Renseigne les critères manquants d'une commande incomplète.

        C'est le geste qui débloque la planification. Il n'est pas
        automatisable : l'information vient du client, pas du fichier.

        La saisie peut être partielle — le dispatcheur remplit ce qu'il
        sait, la commande reste incomplète tant qu'il manque un critère.
        Elle bascule d'elle-même en `EN_ATTENTE` au quatrième renseigné.
        """
        commande = self._exiger_commande(id_commande)
        if commande.statut is not StatutCommande.INCOMPLETE:
            raise ValueError(
                f"Commande {id_commande} : statut {commande.statut.value}, "
                f"elle est déjà classée ; utiliser modifier_commande() pour "
                f"changer un critère"
            )
        return self._ecrire_criteres(commande, criteres)

    def modifier_commande(self, id_commande: str, **criteres) -> Commande:
        """Change un ou plusieurs critères d'une commande déjà classée.

        Cas réel : le client rappelle et change son niveau de service, ou
        signale que le lot est finalement fragile. Autorisé tant que la
        marchandise n'est pas partie ; une commande en cours de route ou
        livrée n'est plus modifiable, sinon le plan décrirait une réalité
        qui n'existe pas.

        L'agent ne replanifie pas : ce n'est pas son rôle. C'est le
        `CoordinatorAgent` qui décide qu'un changement vaut un nouveau
        calcul.
        """
        commande = self._exiger_commande(id_commande)
        if commande.statut not in STATUTS_MODIFIABLES:
            raise ValueError(
                f"Commande {id_commande} : statut {commande.statut.value}, "
                f"une commande dont la marchandise est partie ou livrée ne "
                f"peut plus être reclassée"
            )
        if not criteres:
            raise ValueError(
                f"Commande {id_commande} : aucun critère fourni à modifier"
            )
        return self._ecrire_criteres(commande, criteres)

    def criteres_attendus(self, id_commande: str) -> dict[str, list[str]]:
        """Ce que l'interface doit demander, et les valeurs qu'elle peut proposer.

        L'écran de saisie ne réinvente pas la liste des valeurs : il la
        demande ici. Un champ de texte libre laisserait entrer n'importe
        quoi ; une liste construite à partir du domaine ne le peut pas.
        """
        commande = self._exiger_commande(id_commande)
        return {
            critere: valeurs_possibles(critere)
            for critere in commande.criteres_manquants
        }

    # --- Modifications d'état ---

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
        lieu d'être perdues. Une commande incomplète, elle, ne revient
        pas dans le vivier : elle retourne à la file de saisie.
        """
        commande = self._exiger_commande(id_commande)
        if commande.statut is StatutCommande.LIVREE:
            raise ValueError(
                f"Commande {id_commande} : déjà livrée, elle ne peut pas "
                f"revenir en attente"
            )
        commande.statut = StatutCommande.EN_ATTENTE
        commande.vehicule_assigne = None
        commande.rafraichir_statut()

    # --- Interne ---

    def _ecrire_criteres(self, commande: Commande, criteres: dict) -> Commande:
        """Écrit des critères sur une commande, après conversion et contrôle.

        Rien n'est écrit tant que **tout** n'a pas été validé : une
        saisie à moitié appliquée laisserait la commande dans un état
        que personne n'a voulu.
        """
        valides = {
            nom: convertir_critere(nom, valeur)
            for nom, valeur in criteres.items()
            if valeur is not None
        }
        for nom, valeur in valides.items():
            setattr(commande, nom, valeur)
        commande.rafraichir_statut()
        return commande

    def _exiger_commande(self, id_commande: str) -> Commande:
        """Retrouve une commande, ou lève une exception si elle n'existe pas."""
        commande = self.trouver_commande_par_id(id_commande)
        if commande is None:
            raise ValueError(f"Commande inconnue : {id_commande}")
        return commande
