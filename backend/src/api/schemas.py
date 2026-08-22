from typing import Literal

from pydantic import BaseModel, Field


# --- Entrées ---

class DemandeConnexion(BaseModel):
    """Identifiants présentés au guichet."""

    identifiant: str = Field(min_length=1, max_length=64)
    mot_de_passe: str = Field(min_length=1, max_length=256)


class DemandeCriteres(BaseModel):
    """Classification d'une commande, saisie par le dispatcheur.

    Les quatre champs sont facultatifs : le dispatcheur peut renseigner
    ce qu'il sait et revenir plus tard. La commande reste incomplète tant
    qu'il manque un critère — c'est le domaine qui en décide, pas l'API.

    Les valeurs sont contraintes ici *et* revérifiées par le domaine.
    Ce n'est pas une redondance inutile : l'API peut être contournée, le
    domaine non.
    """

    niveau_service: Literal["express", "standard", "economique"] | None = None
    type_client: Literal["grand_compte", "courant"] | None = None
    fragilite: Literal["standard", "fragile", "tres_fragile"] | None = None
    confidentialite: Literal["normale", "sensible"] | None = None


class DemandeIncident(BaseModel):
    """Un événement déclaré par le dispatcheur.

    Un seul point d'entrée pour les six incidents plutôt que six
    adresses : ils partagent la même conséquence — replanifier et
    mesurer l'écart de Z — et c'est cette conséquence qui compte.
    """

    type: Literal[
        "panne", "reparation", "blocage", "deblocage", "congestion", "attente"
    ]
    vehicule: str | None = None
    origine: str | None = None
    destination: str | None = None
    niveau: float | None = Field(default=None, ge=1.0, le=5.0)
    duree_min: float | None = Field(default=None, ge=0.0, le=2880.0)


class DemandeHeureDepart(BaseModel):
    """Heure de départ appliquée au réseau, de 0 à 23."""

    heure: int = Field(ge=0, le=23)


# --- Sorties ---

class ReponseConnexion(BaseModel):
    """Ce que reçoit un client qui vient de se connecter.

    Le jeton est la seule chose qui compte ; le rôle et le véhicule sont
    renvoyés pour que l'interface sache quoi afficher — pas pour qu'elle
    décide de ses droits. Les droits se vérifient à chaque requête, côté
    serveur.
    """

    jeton: str
    identifiant: str
    role: str
    vehicule: str
    expire_dans_min: float


class Rejet(BaseModel):
    commande: str
    motif: str


class TourneePubliee(BaseModel):
    vehicule: str
    modele: str
    arrets: list[str]
    itineraire: list[str]
    commandes: list[dict]
    distance_km: float
    duree_min: float
    conduite_min: float
    jours: int
    charge_kg: float
    retard_pondere: float
    risque_fragilite: float


class PlanPublie(BaseModel):
    score: dict
    tournees: list[TourneePubliee]
    rejets: list[Rejet]
    heure_depart: int | None
    commandes_a_completer: dict[str, list[str]]


class FeuilleDeRoute(BaseModel):
    """La mission d'un véhicule, telle que le demandeur a le droit de la voir."""

    vehicule: str
    modele: str
    arrets: list[str]
    itineraire: list[str]
    commandes: list[dict]


class EvenementPublie(BaseModel):
    numero: int
    type: str
    description: str
    z_avant: float | None
    z_apres: float | None
    variation: float | None
    auteur: str
