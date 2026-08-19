"""Agent responsable du réseau : graphe, itinéraires, distances.

Seul module du système à importer networkx. Les autres agents lui posent
des questions en langage métier — « combien de temps de X à Y » — et
n'ont jamais à connaître ni graphe ni algorithme. Le jour où Dijkstra
est remplacé par autre chose, ce fichier est le seul à changer.

Deux notions de temps, à ne pas confondre :

- le **temps écoulé** (`temps_trajet`) : tout ce qui sépare le départ de
  l'arrivée — roulage, congestion, attente à la frontière, manutention
  aux noeuds traversés. C'est lui qui décide si un délai est tenu.
- le **temps de conduite** (`temps_conduite`) : les seules minutes où le
  conducteur tient le volant. Attendre au port ou traverser sur un ferry
  n'est pas conduire. C'est lui, et lui seul, qui se compare à la limite
  réglementaire de 9 h par jour.

Les confondre conduirait à interdire une traversée de nuit en ferry sous
prétexte de temps de conduite, alors que le conducteur y dort.
"""

import networkx as nx

from src.models.noeud import Noeud
from src.models.route import ModeTransport, TronconRoute


class CheminIntrouvable(Exception):
    """Aucun itinéraire praticable entre deux noeuds.

    Exception et non retour `None` : un réseau coupé par un incident est
    un événement métier grave que l'appelant doit traiter explicitement.
    Un `None` se laisse oublier, pas une exception.
    """


class RouteAgent:
    """Répond aux questions d'itinéraire sur le réseau de transport."""

    def __init__(self, noeuds: list[Noeud], troncons: list[TronconRoute]) -> None:
        self.noeuds = {noeud.id: noeud for noeud in noeuds}
        self.troncons = troncons
        self.rafraichir()

    # --- Construction ---

    def rafraichir(self) -> None:
        """Reconstruit le graphe à partir de l'état courant des tronçons.

        À appeler après chaque intervention du `TrafficAgent`. C'est le
        mécanisme même de la réoptimisation dynamique : le graphe est une
        photographie du réseau, pas une donnée figée.

        Le graphe est **non orienté** : les données ne saisissent qu'un
        sens par liaison, un graphe orienté rendrait le problème
        infaisable. Un tronçon bloqué est **absent** du graphe, et non
        pondéré à l'infini : avec un poids énorme, l'algorithme
        renverrait quand même un chemin passant par la route barrée.
        """
        self.graphe = nx.Graph()
        self.graphe.add_nodes_from(self.noeuds)

        for troncon in self.troncons:
            if not troncon.praticable:
                continue
            self.graphe.add_edge(
                troncon.origine,
                troncon.destination,
                temps=troncon.temps_reel_min,
                conduite=self._conduite_du_troncon(troncon),
                distance=troncon.distance_km,
                cout=troncon.cout_fixe_dh,
            )
        self._chemins = {}

    @staticmethod
    def _conduite_du_troncon(troncon: TronconRoute) -> float:
        """Minutes réellement conduites sur ce tronçon.

        Une traversée maritime ne compte pas : le conducteur est
        passager. L'attente au franchissement non plus : il patiente.
        """
        if troncon.mode is not ModeTransport.ROUTIER:
            return 0.0
        return troncon.temps_base_min * troncon.niveau_trafic

    # --- Itinéraires ---

    def chemin_existe(self, origine: str, destination: str) -> bool:
        """Garde à appeler avant toute mesure, quand le doute est permis."""
        self._exiger_noeuds(origine, destination)
        return nx.has_path(self.graphe, origine, destination)

    def plus_court_chemin(self, origine: str, destination: str) -> list[str]:
        """Suite de noeuds la plus rapide, de l'origine à la destination.

        Le critère est le temps écoulé sur les tronçons. Les durées de
        traitement aux noeuds sont ajoutées ensuite, sur le chemin
        retenu : c'est une approximation assumée — un chemin passant par
        un port pourrait, en toute rigueur, être écarté au profit d'un
        détour plus long mais sans formalités.
        """
        self._exiger_noeuds(origine, destination)
        if origine == destination:
            return [origine]

        memo = (origine, destination)
        if memo not in self._chemins:
            try:
                self._chemins[memo] = nx.shortest_path(
                    self.graphe, origine, destination, weight="temps"
                )
            except nx.NetworkXNoPath as absence:
                raise CheminIntrouvable(
                    f"Aucun itinéraire praticable de {origine} vers "
                    f"{destination} : le réseau est coupé"
                ) from absence
        return list(self._chemins[memo])

    def itineraire_complet(self, arrets: list[str]) -> list[str]:
        """Déplie une suite d'arrêts en tous les noeuds réellement traversés.

        L'optimiseur raisonne sur les arrêts (« Casablanca puis Madrid »),
        la carte du chauffeur a besoin du détail (« ... par Rabat, Tanger,
        Tanger Med, Algésiras »). On ne stocke pas les deux : on déplie
        à la demande.
        """
        if len(arrets) < 2:
            return list(arrets)

        itineraire = [arrets[0]]
        for depart, arrivee in zip(arrets, arrets[1:]):
            # On retire le premier noeud de chaque segment : c'est le
            # dernier du segment précédent, il serait compté deux fois.
            itineraire.extend(self.plus_court_chemin(depart, arrivee)[1:])
        return itineraire

    def noeuds_accessibles(self, depuis: str) -> set[str]:
        """Tous les noeuds encore atteignables depuis un point donné."""
        self._exiger_noeuds(depuis)
        return set(nx.node_connected_component(self.graphe, depuis))

    # --- Mesures ---

    def temps_trajet(self, origine: str, destination: str) -> float:
        """Temps écoulé entre deux noeuds, en minutes.

        Somme des temps des tronçons empruntés, plus la durée de
        traitement de chaque noeud atteint. Le noeud de départ n'est pas
        compté : son chargement appartient à la préparation de la
        tournée, pas au trajet.
        """
        chemin = self.plus_court_chemin(origine, destination)
        return self._sommer(chemin, "temps") + sum(
            self.noeuds[identifiant].duree_traitement_min
            for identifiant in chemin[1:]
        )

    def temps_conduite(self, origine: str, destination: str) -> float:
        """Minutes de conduite effective entre deux noeuds.

        Ni les attentes, ni les traversées maritimes, ni la manutention.
        C'est la grandeur à comparer au quota journalier du conducteur.
        """
        return self._sommer(self.plus_court_chemin(origine, destination), "conduite")

    def distance_trajet(self, origine: str, destination: str) -> float:
        """Distance parcourue entre deux noeuds, en kilomètres."""
        return self._sommer(self.plus_court_chemin(origine, destination), "distance")

    def cout_trajet(self, origine: str, destination: str) -> float:
        """Coûts fixes du trajet (péages, ferry), en dirhams."""
        return self._sommer(self.plus_court_chemin(origine, destination), "cout")

    def matrice_temps(self, identifiants: list[str]) -> dict[tuple[str, str], float]:
        """Temps écoulé entre toutes les paires d'une liste de noeuds.

        Utile à un solveur, qui a besoin de la matrice complète plutôt
        que d'appels un par un. Les paires sans chemin sont absentes du
        résultat : à l'appelant de constater le manque.
        """
        matrice = {}
        for origine in identifiants:
            for destination in identifiants:
                if origine == destination:
                    matrice[(origine, destination)] = 0.0
                    continue
                try:
                    matrice[(origine, destination)] = self.temps_trajet(
                        origine, destination
                    )
                except CheminIntrouvable:
                    continue
        return matrice

    # --- Interne ---

    def _sommer(self, chemin: list[str], attribut: str) -> float:
        """Additionne un attribut d'arête le long d'un chemin."""
        return sum(
            self.graphe[depart][arrivee][attribut]
            for depart, arrivee in zip(chemin, chemin[1:])
        )

    def _exiger_noeuds(self, *identifiants: str) -> None:
        """Un identifiant inconnu est un bug de l'appelant, pas un cas métier."""
        for identifiant in identifiants:
            if identifiant not in self.noeuds:
                raise ValueError(f"Noeud inconnu : {identifiant}")