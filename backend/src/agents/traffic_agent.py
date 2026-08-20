"""Agent responsable des conditions de circulation et de franchissement.

Il ne connaît que les tronçons : ni commandes, ni véhicules, ni graphe.
Il modifie l'état courant du réseau (trafic, attente aux frontières,
blocages), jamais les données de référence (distance, temps de base).

Deux façons de faire varier le trafic, à ne pas confondre :

- **le profil horaire** (`appliquer_profil_horaire`) : la circulation
  normale d'une journée ordinaire, qui dépend de l'heure de départ et du
  type de tronçon. C'est le régime de base, il s'applique à tout le
  réseau d'un coup.
- **l'incident déclaré** (`mettre_a_jour_trafic`) : un accident, un
  chantier, une manifestation. Il vise un tronçon précis et vient
  écraser le régime de base sur celui-là seulement.
"""

from src.models.route import ModeTransport, TronconRoute, coefficient_horaire


class TrafficAgent:
    """Gère les conditions de circulation du réseau de transport."""

    def __init__(self, troncons: list[TronconRoute]) -> None:
        self.troncons = troncons
        # Heure de départ actuellement appliquée au réseau, ou None tant
        # qu'aucun profil n'a été posé : le réseau tourne alors sur les
        # niveaux de trafic écrits dans le fichier.
        self.heure_appliquee: int | None = None

    # --- Lectures ---

    def troncons_praticables(self) -> list[TronconRoute]:
        """Les tronçons empruntables, c'est-à-dire non bloqués."""
        return [
            troncon for troncon in self.troncons
            if troncon.praticable
        ]

    def troncons_transfrontaliers(self) -> list[TronconRoute]:
        """Les tronçons qui font changer de pays.

        Ce sont les points de fragilité de la chaîne internationale :
        c'est là que se concentrent les attentes et les blocages.
        """
        return [
            troncon for troncon in self.troncons
            if troncon.franchit_frontiere
        ]

    def troncons_congestionnes(self, seuil: float = 1.2) -> list[TronconRoute]:
        """Les tronçons dont le trafic dépasse un seuil donné.

        Sert à expliquer un plan : quand Z monte après un changement
        d'heure de départ, cette liste dit exactement où.
        """
        return [
            troncon for troncon in self.troncons
            if troncon.niveau_trafic >= seuil
        ]

    def trouver_troncon(
        self, origine: str, destination: str
    ) -> TronconRoute | None:
        """Retourne le tronçon reliant ces deux noeuds, ou None.

        Un tronçon n'a pas d'identifiant propre : c'est le couple de
        noeuds qui l'identifie. La recherche est symétrique, parce que le
        réseau est modélisé par un graphe non orienté : une route saisie
        dans le sens Casablanca -> Rabat se parcourt aussi en sens
        inverse, et une recherche stricte ferait échouer un blocage sur
        deux.
        """
        for troncon in self.troncons:
            memes_extremites = {troncon.origine, troncon.destination} == {
                origine, destination
            }
            if memes_extremites:
                return troncon
        return None

    # --- Modifications ---

    def appliquer_profil_horaire(self, heure: int) -> None:
        """Règle tout le réseau sur la circulation d'une heure de départ.

        C'est la réponse à « prendre en considération le trafic » : le
        trafic n'est plus une valeur figée qu'un opérateur déclare, il
        découle de l'heure à laquelle on décide de partir. Une même
        journée de commandes planifiée à 6 h et à 8 h ne produit plus le
        même plan, ni le même Z.

        Les traversées maritimes sont laissées de côté : leur aléa est
        l'attente d'embarquement, pas la congestion routière — et le
        modèle interdit d'ailleurs de leur donner un niveau de trafic.
        """
        if not 0 <= heure <= 23:
            raise ValueError(
                f"Heure de départ invalide : {heure} (attendu entre 0 et 23)"
            )
        for troncon in self.troncons:
            if troncon.mode is ModeTransport.MARITIME:
                continue
            troncon.niveau_trafic = coefficient_horaire(
                troncon.profil_trafic, heure
            )
        self.heure_appliquee = heure

    def bloquer_troncon(self, origine: str, destination: str) -> None:
        """Rend un tronçon impraticable (scénario 3 du cahier des charges)."""
        troncon = self._exiger_troncon(origine, destination)
        troncon.bloquee = True

    def debloquer_troncon(self, origine: str, destination: str) -> None:
        """Rouvre un tronçon précédemment bloqué."""
        troncon = self._exiger_troncon(origine, destination)
        troncon.bloquee = False

    def mettre_a_jour_trafic(
        self, origine: str, destination: str, niveau: float
    ) -> None:
        """Modifie le multiplicateur de trafic d'un tronçon routier.

        Incident ponctuel : il écrase, sur ce seul tronçon, le niveau
        posé par le profil horaire. Reposer un profil ensuite effacerait
        l'incident — c'est voulu, un profil décrit une journée normale.

        La garde sur le niveau n'est pas redondante avec celle du modèle :
        `__post_init__` ne s'exécute qu'à la construction de l'objet, pas
        lors des modifications qui suivent.
        """
        if niveau < 1.0:
            raise ValueError(
                f"Niveau de trafic invalide : {niveau} "
                f"(attendu supérieur ou égal à 1.0)"
            )
        troncon = self._exiger_troncon(origine, destination)
        if troncon.mode is ModeTransport.MARITIME:
            raise ValueError(
                f"Tronçon {origine} -> {destination} : traversée maritime, "
                f"la congestion routière ne s'y applique pas ; utiliser "
                f"mettre_a_jour_attente_frontiere"
            )
        troncon.niveau_trafic = niveau

    def mettre_a_jour_attente_frontiere(
        self, origine: str, destination: str, duree_min: float
    ) -> None:
        """Modifie l'attente de franchissement d'un tronçon transfrontalier.

        C'est l'aléa dominant de la partie internationale : la file au
        contrôle douanier ou l'attente d'embarquement pèsent plus lourd
        sur un Tanger - Algeciras que la congestion routière.
        """
        if duree_min < 0:
            raise ValueError(
                f"Attente de franchissement invalide : {duree_min} "
                f"(attendu positif ou nul)"
            )
        troncon = self._exiger_troncon(origine, destination)
        if not troncon.franchit_frontiere:
            raise ValueError(
                f"Tronçon {origine} -> {destination} : ne franchit aucune "
                f"frontière, aucune attente de franchissement ne s'y applique"
            )
        troncon.attente_frontiere_min = duree_min

    # --- Interne ---

    def _exiger_troncon(self, origine: str, destination: str) -> TronconRoute:
        """Retrouve un tronçon, ou lève une exception s'il n'existe pas.

        Factorise la garde commune aux méthodes de modification :
        chercher sans trouver est normal, mais modifier ce qui n'existe
        pas est un bug de l'appelant.
        """
        troncon = self.trouver_troncon(origine, destination)
        if troncon is None:
            raise ValueError(f"Tronçon inconnu : {origine} -> {destination}")
        return troncon
