"""Traduit les décisions des agents en tracés routiers réels.

Les agents décident d'une suite de noeuds à parcourir ; ce service
demande à un calculateur d'itinéraire la géométrie réelle de la route
entre ces noeuds, pour que la carte du chauffeur affiche le trajet exact
et non un segment droit.

Ce module appartient à la couche de présentation, pas au domaine : aucun
agent ne l'importe. Le sens inverse est vrai — il consomme les objets du
domaine sans jamais les modifier.

Trois garanties, dans cet ordre d'importance :

1. **Cache disque.** La géométrie d'une route ne change pas : la N1 entre
   Casablanca et Rabat sera au même endroit demain. Chaque tronçon n'est
   donc interrogé qu'une fois dans la vie du projet, puis relu depuis
   `data/geometries.json`. Une fois le cache constitué, l'application
   n'a plus besoin d'Internet — condition indispensable pour une
   démonstration en salle.
2. **Repli systématique.** Pas de clé d'API, pas de réseau, service en
   panne : on retombe sur le segment droit et on le signale. La carte
   s'affiche toujours, dégradée mais jamais vide.
3. **Traversées maritimes exclues.** Aucun calculateur routier ne trace
   Tanger Med - Algésiras : il n'y a pas de route sur la mer. Le tronçon
   maritime est tracé en ligne droite, ce qui est d'ailleurs exact — un
   ferry traverse en ligne droite.
"""

import json
import urllib.error
import urllib.request
from dataclasses import dataclass
from pathlib import Path

from src.models.noeud import Noeud
from src.models.route import ModeTransport, TronconRoute

CACHE_PAR_DEFAUT = Path("data/geometries.json")
DELAI_REQUETE_S = 20

# Profil poids lourd : un semi-remorque n'emprunte pas les mêmes voies
# qu'une voiture (gabarit, interdictions, tonnage). Utiliser le profil
# voiture donnerait des trajets que le chauffeur ne pourrait pas suivre.
URL_ORS = "https://api.openrouteservice.org/v2/directions/driving-hgv/geojson"
URL_OSRM = "https://router.project-osrm.org/route/v1/driving/{coords}"


@dataclass
class Trace:
    """Le tracé d'un tronçon, tel qu'il sera dessiné.

    `points` est une liste de couples (latitude, longitude) : c'est
    directement ce qu'attend une carte Leaflet.
    """

    points: list[tuple[float, float]]
    distance_km: float
    duree_min: float
    source: str          # "ors", "osrm", "maritime" ou "droit"

    @property
    def approximatif(self) -> bool:
        """Vrai si le tracé n'est pas la vraie géométrie de la route."""
        return self.source == "droit"


class ServiceGeometrie:
    """Fournit la géométrie routière réelle entre deux noeuds du réseau."""

    def __init__(
        self,
        noeuds: list[Noeud],
        troncons: list[TronconRoute],
        cle_api: str | None = None,
        fournisseur: str = "ors",
        chemin_cache: Path = CACHE_PAR_DEFAUT,
    ) -> None:
        self.noeuds = {noeud.id: noeud for noeud in noeuds}
        self.maritimes = {
            self._cle(t.origine, t.destination)
            for t in troncons
            if t.mode is ModeTransport.MARITIME
        }
        self.cle_api = cle_api
        self.fournisseur = fournisseur
        self.chemin_cache = Path(chemin_cache)
        self.cache = self._charger_cache()
        self.appels_reseau = 0

    # --- Interface publique ---

    def tracer(self, origine: str, destination: str) -> Trace:
        """Retourne le tracé entre deux noeuds voisins.

        L'ordre des deux noeuds n'entre pas dans la clé de cache : la
        route est la même dans les deux sens, on la mémorise une fois et
        on inverse les points au besoin. C'est cohérent avec le graphe
        non orienté du modèle.
        """
        cle = self._cle(origine, destination)
        inverse = origine > destination

        if cle in self.cache:
            return self._depuis_cache(cle, inverse)

        if cle in self.maritimes:
            trace = self._droit(origine, destination, source="maritime")
        else:
            trace = self._interroger(origine, destination)

        # On ne mémorise jamais un repli : un segment droit n'est pas une
        # connaissance acquise, c'est un échec. Le mettre en cache
        # empêcherait définitivement de récupérer la vraie géométrie au
        # prochain lancement, celui où la clé d'API sera enfin là.
        if not trace.approximatif:
            self._memoriser(cle, trace, inverse)
        return trace

    def tracer_itineraire(self, itineraire: list[str]) -> list[Trace]:
        """Trace une suite complète de noeuds, tronçon par tronçon.

        `itineraire` est la liste rendue par `RouteAgent.itineraire_complet`:
        tous les noeuds traversés, pas seulement les arrêts.
        """
        return [
            self.tracer(depart, arrivee)
            for depart, arrivee in zip(itineraire, itineraire[1:])
        ]

    def sauver_cache(self) -> None:
        """Écrit le cache sur disque. À appeler après une série de tracés."""
        self.chemin_cache.parent.mkdir(parents=True, exist_ok=True)
        self.chemin_cache.write_text(
            json.dumps(self.cache, ensure_ascii=False), encoding="utf-8"
        )

    # --- Appels au calculateur d'itinéraire ---

    def _interroger(self, origine: str, destination: str) -> Trace:
        """Demande la géométrie réelle au fournisseur configuré.

        Toute erreur — pas de clé, pas de réseau, service indisponible,
        aucun itinéraire trouvé — mène au segment droit. Le service ne
        lève jamais d'exception : une carte dégradée vaut mieux qu'une
        application qui s'arrête.
        """
        try:
            if self.fournisseur == "ors":
                if not self.cle_api:
                    return self._droit(origine, destination)
                return self._appeler_ors(origine, destination)
            return self._appeler_osrm(origine, destination)
        except (urllib.error.URLError, OSError, KeyError, IndexError, ValueError):
            return self._droit(origine, destination)

    def _appeler_ors(self, origine: str, destination: str) -> Trace:
        """OpenRouteService, profil poids lourd (clé d'API gratuite requise)."""
        corps = json.dumps({
            "coordinates": [
                self._lon_lat(origine), self._lon_lat(destination),
            ]
        }).encode()
        requete = urllib.request.Request(
            URL_ORS, data=corps,
            headers={
                "Authorization": self.cle_api,
                "Content-Type": "application/json",
            },
        )
        self.appels_reseau += 1
        with urllib.request.urlopen(requete, timeout=DELAI_REQUETE_S) as reponse:
            donnees = json.loads(reponse.read())

        trait = donnees["features"][0]
        resume = trait["properties"]["summary"]
        return Trace(
            points=[(lat, lon) for lon, lat in trait["geometry"]["coordinates"]],
            distance_km=round(resume["distance"] / 1000, 1),
            duree_min=round(resume["duration"] / 60),
            source="ors",
        )

    def _appeler_osrm(self, origine: str, destination: str) -> Trace:
        """OSRM public : sans clé, mais profil voiture et sans garantie."""
        coords = "{},{};{},{}".format(
            *self._lon_lat(origine), *self._lon_lat(destination)
        )
        url = URL_OSRM.format(coords=coords) + "?overview=full&geometries=geojson"
        self.appels_reseau += 1
        with urllib.request.urlopen(url, timeout=DELAI_REQUETE_S) as reponse:
            donnees = json.loads(reponse.read())

        route = donnees["routes"][0]
        return Trace(
            points=[(lat, lon) for lon, lat in route["geometry"]["coordinates"]],
            distance_km=round(route["distance"] / 1000, 1),
            duree_min=round(route["duration"] / 60),
            source="osrm",
        )

    # --- Repli et utilitaires ---

    def _droit(self, origine: str, destination: str, source: str = "droit") -> Trace:
        """Segment droit entre deux noeuds : le repli, et le cas maritime.

        La distance et la durée ne sont pas recalculées : on garde celles
        des données de référence, qui restent la vérité du modèle.
        """
        a, b = self.noeuds[origine], self.noeuds[destination]
        return Trace(
            points=[(a.latitude, a.longitude), (b.latitude, b.longitude)],
            distance_km=0.0, duree_min=0.0, source=source,
        )

    def _lon_lat(self, id_noeud: str) -> list[float]:
        """Coordonnées au format attendu par les API : longitude d'abord."""
        noeud = self.noeuds[id_noeud]
        return [noeud.longitude, noeud.latitude]

    @staticmethod
    def _cle(origine: str, destination: str) -> str:
        """Clé de cache indépendante du sens de parcours."""
        return "|".join(sorted((origine, destination)))

    def _charger_cache(self) -> dict:
        if not self.chemin_cache.is_file():
            return {}
        return json.loads(self.chemin_cache.read_text(encoding="utf-8"))

    def _memoriser(self, cle: str, trace: Trace, inverse: bool) -> None:
        """Range un tracé dans le cache, toujours dans le sens de la clé."""
        points = list(reversed(trace.points)) if inverse else trace.points
        self.cache[cle] = {
            "points": points,
            "distance_km": trace.distance_km,
            "duree_min": trace.duree_min,
            "source": trace.source,
        }

    def _depuis_cache(self, cle: str, inverse: bool) -> Trace:
        entree = self.cache[cle]
        points = [tuple(p) for p in entree["points"]]
        return Trace(
            points=list(reversed(points)) if inverse else points,
            distance_km=entree["distance_km"],
            duree_min=entree["duree_min"],
            source=entree["source"],
        )