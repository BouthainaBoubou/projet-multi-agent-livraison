"""Agent responsable des conditions de circulation.

Il ne connaît que les tronçons : ni commandes, ni véhicules, ni graphe.
Il modifie l'état courant du réseau (trafic, blocages), jamais les
données de référence (distance, temps de base).
"""

from src.models.route import TronconRoute


class TrafficAgent:
    """Gère les conditions de circulation du réseau routier."""

    def __init__(self, troncons: list[TronconRoute]) -> None:
        self.troncons = troncons

    # --- Lectures ---

    def troncons_praticables(self) -> list[TronconRoute]:
        """Les tronçons empruntables, c'est-à-dire non bloqués."""
        return [
            troncon for troncon in self.troncons
            if troncon.praticable
        ]

    def trouver_troncon(
        self, origine: str, destination: str
    ) -> TronconRoute | None:
        """Retourne le tronçon reliant ces deux noeuds, ou None.

        Un tronçon n'a pas d'identifiant propre : c'est le couple
        (origine, destination) qui l'identifie. La recherche prend donc
        deux paramètres au lieu d'un.
        """
        for troncon in self.troncons:
            if troncon.origine == origine and troncon.destination == destination:
                return troncon
        return None

    # --- Modifications ---

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
        """Modifie le multiplicateur de trafic d'un tronçon.

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
        troncon.niveau_trafic = niveau

    # --- Interne ---

    def _exiger_troncon(self, origine: str, destination: str) -> TronconRoute:
        """Retrouve un tronçon, ou lève une exception s'il n'existe pas.

        Factorise la garde commune aux trois méthodes de modification :
        chercher sans trouver est normal, mais modifier ce qui n'existe
        pas est un bug de l'appelant.
        """
        troncon = self.trouver_troncon(origine, destination)
        if troncon is None:
            raise ValueError(f"Tronçon inconnu : {origine} -> {destination}")
        return troncon