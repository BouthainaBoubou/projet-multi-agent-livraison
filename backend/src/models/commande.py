"""Modèle représentant une commande de livraison.

une commande n'est plus décrite par un
poids et une priorité saisie à la main. Elle porte **quatre critères de
classification** explicites, rangés en trois familles selon ce qu'ils
déclenchent dans le système :

1. **Ordonnancement** — `niveau_service` et `type_client` déterminent la
   priorité. Celle-ci n'est plus une donnée d'entrée : elle est calculée
   par une grille documentée (`GRILLE_PRIORITE`), donc justifiable.
2. **Éligibilité** — `fragilite` détermine quels véhicules peuvent
   prendre la commande et combien de manutentions elle supporte.
3. **Visibilité** — `confidentialite` détermine ce que chaque rôle a le
   droit de voir.

**Aucun critère n'a de valeur par défaut.** Une commande dont un critère
manque naît au statut `INCOMPLETE` : elle existe, elle est visible, mais
aucun agent ne la planifie tant que le dispatcheur ne l'a pas complétée.
C'est un choix : une valeur par défaut inventée par le programme serait
une décision métier prise à la place de l'humain, et personne ne saurait
plus laquelle des deux a eu lieu.
"""

from dataclasses import dataclass, field
from enum import Enum


class Priorite(Enum):
    """Niveau d'urgence d'une commande.

    N'est plus saisi : c'est le résultat de `GRILLE_PRIORITE`. La valeur
    numérique est volontairement croissante avec l'urgence : elle sert à
    trier et à pondérer les retards dans la fonction objectif.
    """
    BASSE = 1
    NORMALE = 2
    HAUTE = 3


class NiveauService(Enum):
    """Engagement de délai vendu au client (critère d'ordonnancement).

    Vient du contrat, pas de la marchandise : deux lots identiques
    peuvent être vendus l'un en express, l'autre en économique.
    """
    EXPRESS = "express"
    STANDARD = "standard"
    ECONOMIQUE = "economique"


class TypeClient(Enum):
    """Statut commercial du donneur d'ordre (critère d'ordonnancement)."""
    GRAND_COMPTE = "grand_compte"   # contrat-cadre, volumes réguliers
    COURANT = "courant"             # expédition ponctuelle


class Fragilite(Enum):
    """Classe de manutention de la marchandise (critère d'éligibilité).

    Le système ne modélise pas la nature du produit — il reste un
    transporteur de marchandises générales. Il modélise seulement la
    précaution que ce produit exige, ce qui suffit à choisir un véhicule
    et à limiter les ruptures de charge.
    """
    STANDARD = "standard"
    FRAGILE = "fragile"
    TRES_FRAGILE = "tres_fragile"


class Confidentialite(Enum):
    """Niveau de protection de l'information portée par la commande.

    Critère de visibilité, sans aucun effet sur le calcul des tournées :
    une commande sensible ne coûte pas plus cher à transporter, elle
    s'affiche différemment selon qui regarde.
    """
    NORMALE = "normale"
    SENSIBLE = "sensible"


class TypeLivraison(Enum):
    """Portée géographique d'une commande.

    Donnée dérivée des pays de l'origine et de la destination. Elle est
    matérialisée ici plutôt que recalculée partout, mais une seule
    autorité la renseigne : le loader, au moment du chargement.
    """
    NATIONALE = "nationale"
    INTERNATIONALE = "internationale"


class StatutCommande(Enum):
    """Cycle de vie d'une commande."""
    INCOMPLETE = "incomplete"   # créée, mais un critère de classification manque
    EN_ATTENTE = "en_attente"   # complète, pas encore affectée à un véhicule
    ASSIGNEE = "assignee"       # affectée par l'agent d'optimisation
    EN_COURS = "en_cours"       # le véhicule est en route
    LIVREE = "livree"           # terminée, dans les délais ou non
    ECHOUEE = "echouee"         # impossible à livrer


# --- Les trois tables qui donnent leur sens aux critères ---

# Famille 1 : ordonnancement. Un client courant en économique n'a aucune
# raison de passer devant un grand compte en express — et cette phrase
# est maintenant écrite quelque part, au lieu d'être une intuition.
GRILLE_PRIORITE: dict[tuple[NiveauService, TypeClient], Priorite] = {
    (NiveauService.EXPRESS, TypeClient.GRAND_COMPTE): Priorite.HAUTE,
    (NiveauService.EXPRESS, TypeClient.COURANT): Priorite.HAUTE,
    (NiveauService.STANDARD, TypeClient.GRAND_COMPTE): Priorite.HAUTE,
    (NiveauService.STANDARD, TypeClient.COURANT): Priorite.NORMALE,
    (NiveauService.ECONOMIQUE, TypeClient.GRAND_COMPTE): Priorite.NORMALE,
    (NiveauService.ECONOMIQUE, TypeClient.COURANT): Priorite.BASSE,
}

# Famille 2 : éligibilité. Chaque arrêt intermédiaire avant la livraison
# oblige à déplacer le chargement pour atteindre les colis du fond.
# `None` signifie « pas de limite ».
#
# Les deux classes ne sont pas traitées de la même façon, et c'est
# volontaire :
# - le **très fragile** est tenu par une contrainte dure — une seule
#   manutention, et un véhicule équipé. Une contrainte, parce qu'aucune
#   économie de kilomètres ne rachète un lot cassé.
# - le **fragile** est tenu par la pénalité de la fonction objectif. La
#   limite de 4 n'est qu'un plafond de sécurité : elle n'est presque
#   jamais atteinte, c'est le coût qui fait le travail. Descendre ce
#   plafond à 3 a été essayé — il fait rejeter une commande de plus et
#   coûte 1 500 km, pour un gain de sécurité nul sur des lots que la
#   pénalité éloignait déjà du fond du camion.
MANUTENTIONS_MAX: dict[Fragilite, int | None] = {
    Fragilite.STANDARD: None,
    Fragilite.FRAGILE: 4,
    Fragilite.TRES_FRAGILE: 1,
}

# Poids du risque de casse dans la fonction objectif, par manutention.
COEFFICIENT_RISQUE: dict[Fragilite, float] = {
    Fragilite.STANDARD: 0.0,
    Fragilite.FRAGILE: 1.0,
    Fragilite.TRES_FRAGILE: 3.0,
}

# Les quatre critères que le système exige avant toute planification.
CRITERES_CLASSIFICATION: tuple[str, ...] = (
    "niveau_service", "type_client", "fragilite", "confidentialite",
)

_ENUM_DU_CRITERE: dict[str, type[Enum]] = {
    "niveau_service": NiveauService,
    "type_client": TypeClient,
    "fragilite": Fragilite,
    "confidentialite": Confidentialite,
}


def valeurs_possibles(critere: str) -> list[str]:
    """Les valeurs acceptées pour un critère, pour alimenter une liste déroulante.

    L'interface ne doit pas réinventer cette liste : elle la demande ici.
    C'est ce qui garantit qu'un champ de saisie ne pourra jamais produire
    une valeur que le domaine ne connaît pas.
    """
    if critere not in _ENUM_DU_CRITERE:
        raise ValueError(
            f"Critère de classification inconnu : '{critere}' "
            f"(attendu parmi {list(CRITERES_CLASSIFICATION)})"
        )
    return [membre.value for membre in _ENUM_DU_CRITERE[critere]]


def convertir_critere(critere: str, valeur: object) -> Enum:
    """Transforme le texte saisi ou lu dans un CSV en valeur du domaine.

    Une seule fonction fait la conversion, pour que le loader et la
    saisie manuelle acceptent exactement les mêmes valeurs. Une valeur
    inconnue lève une exception : on ne la remplace pas par un défaut,
    sinon une faute de frappe deviendrait une décision métier silencieuse.
    """
    if critere not in _ENUM_DU_CRITERE:
        raise ValueError(
            f"Critère de classification inconnu : '{critere}' "
            f"(attendu parmi {list(CRITERES_CLASSIFICATION)})"
        )
    enumeration = _ENUM_DU_CRITERE[critere]
    if isinstance(valeur, enumeration):
        return valeur

    texte = str(valeur).strip().lower()
    for membre in enumeration:
        if texte in (membre.value, membre.name.lower()):
            return membre
    raise ValueError(
        f"Valeur '{valeur}' inconnue pour le critère '{critere}' "
        f"(attendu parmi {valeurs_possibles(critere)})"
    )


@dataclass
class Commande:
    """Une commande à livrer.

    Structure de données passive : elle porte l'information et garantit
    sa propre cohérence, mais ne contient aucune logique métier.
    """

    # --- Identité ---
    id: str

    # --- Données métier toujours connues à la prise de commande ---
    origine: str                # identifiant du noeud d'enlèvement (hub ou agence)
    destination: str            # identifiant du noeud de livraison
    poids: float                # en kilogrammes
    delai_minutes: int          # délai maximum en minutes depuis l'instant t0

    # --- Critères de classification ---
    # `None` ne veut pas dire « valeur neutre » mais « pas encore
    # renseigné ». Aucun défaut n'est appliqué : c'est le dispatcheur qui
    # tranche, pas le programme.
    niveau_service: NiveauService | None = None
    type_client: TypeClient | None = None
    fragilite: Fragilite | None = None
    confidentialite: Confidentialite | None = None

    # --- Donnée dérivée, renseignée par le loader ---
    type_livraison: TypeLivraison = TypeLivraison.NATIONALE

    # --- État courant ---
    statut: StatutCommande = field(default=StatutCommande.EN_ATTENTE)
    vehicule_assigne: str | None = field(default=None)

    def __post_init__(self) -> None:
        """Vérifie les invariants juste après la construction de l'objet.

        Appelée automatiquement par la dataclass. Si une règle est violée,
        on lève une exception immédiatement (principe fail fast).
        """
        if self.poids <= 0:
            raise ValueError(
                f"Commande {self.id} : le poids doit être strictement positif "
                f"(reçu : {self.poids})"
            )
        if self.delai_minutes <= 0:
            raise ValueError(
                f"Commande {self.id} : le délai doit être strictement positif "
                f"(reçu : {self.delai_minutes})"
            )
        if not self.origine:
            raise ValueError(f"Commande {self.id} : origine vide")
        if not self.destination:
            raise ValueError(f"Commande {self.id} : destination vide")
        if self.origine == self.destination:
            raise ValueError(
                f"Commande {self.id} : origine et destination identiques "
                f"('{self.origine}')"
            )
        self.rafraichir_statut()

    # --- Complétude ---

    def rafraichir_statut(self) -> None:
        """Aligne le statut sur la complétude des critères.

        Appelée à la construction et après chaque saisie. Une commande
        incomplète qui vient d'être complétée entre dans le vivier ; une
        commande en attente à qui l'on retirerait un critère en sortirait.
        """
        if self.criteres_manquants:
            if self.statut in (StatutCommande.INCOMPLETE, StatutCommande.EN_ATTENTE):
                self.statut = StatutCommande.INCOMPLETE
            return
        if self.statut is StatutCommande.INCOMPLETE:
            self.statut = StatutCommande.EN_ATTENTE

    @property
    def criteres_manquants(self) -> list[str]:
        """Les critères de classification encore à saisir, dans l'ordre."""
        return [
            critere for critere in CRITERES_CLASSIFICATION
            if getattr(self, critere) is None
        ]

    @property
    def est_complete(self) -> bool:
        """Vrai si les quatre critères sont renseignés."""
        return not self.criteres_manquants

    # --- Données dérivées des critères ---

    @property
    def priorite(self) -> Priorite:
        """Priorité issue de la grille de classification.

        Lève une exception si la commande est incomplète : c'est la
        garantie technique qu'aucun agent ne peut planifier une commande
        non classée, même par erreur de programmation.
        """
        if not self.est_complete:
            raise ValueError(
                f"Commande {self.id} : priorité indisponible, critères "
                f"manquants {self.criteres_manquants}"
            )
        return GRILLE_PRIORITE[(self.niveau_service, self.type_client)]

    @property
    def manutentions_max(self) -> int | None:
        """Nombre d'arrêts intermédiaires tolérés avant la livraison.

        `None` signifie qu'aucune limite ne s'applique.
        """
        if self.fragilite is None:
            raise ValueError(
                f"Commande {self.id} : fragilité non renseignée"
            )
        return MANUTENTIONS_MAX[self.fragilite]

    @property
    def coefficient_risque(self) -> float:
        """Poids d'une manutention de cette commande dans le risque de casse."""
        if self.fragilite is None:
            raise ValueError(
                f"Commande {self.id} : fragilité non renseignée"
            )
        return COEFFICIENT_RISQUE[self.fragilite]

    @property
    def est_urgente(self) -> bool:
        """Donnée dérivée : ne dépend que des attributs de l'objet."""
        return self.priorite is Priorite.HAUTE

    @property
    def est_internationale(self) -> bool:
        """Vrai si la commande franchit au moins une frontière."""
        return self.type_livraison is TypeLivraison.INTERNATIONALE

    @property
    def est_sensible(self) -> bool:
        """Vrai si l'information de cette commande est à diffusion restreinte."""
        return self.confidentialite is Confidentialite.SENSIBLE

    # --- Restitution filtrée ---

    def vue(self, role: str) -> dict:
        """Ce qu'un rôle donné a le droit de voir de cette commande.

        Le filtrage vit dans le modèle et non dans l'affichage : une
        deuxième interface (API, carte, export) ne peut pas oublier de
        l'appliquer, puisqu'elle n'a pas d'autre chemin vers la donnée.

        - `dispatcheur` : tout, c'est lui qui décide et qui répond.
        - `conducteur` : le strict nécessaire pour livrer. Sur une
          commande sensible, l'identifiant seul — il transporte un colis,
          il n'a pas à savoir ce qu'il transporte ni pour qui.
        """
        if role == "dispatcheur":
            return {
                "id": self.id,
                "origine": self.origine,
                "destination": self.destination,
                "poids": self.poids,
                "delai_minutes": self.delai_minutes,
                "niveau_service": _texte(self.niveau_service),
                "type_client": _texte(self.type_client),
                "fragilite": _texte(self.fragilite),
                "confidentialite": _texte(self.confidentialite),
                "priorite": self.priorite.name if self.est_complete else None,
                "statut": self.statut.value,
                "criteres_manquants": self.criteres_manquants,
                "vehicule_assigne": self.vehicule_assigne,
            }
        if role == "conducteur":
            if self.est_sensible:
                return {
                    "id": self.id,
                    "destination": self.destination,
                    "confidentiel": True,
                }
            return {
                "id": self.id,
                "destination": self.destination,
                "poids": self.poids,
                "fragilite": _texte(self.fragilite),
                "confidentiel": False,
            }
        raise ValueError(
            f"Rôle inconnu : '{role}' (attendu 'dispatcheur' ou 'conducteur')"
        )


def _texte(valeur: Enum | None) -> str | None:
    """Rend une valeur d'énumération affichable, sans masquer son absence."""
    return None if valeur is None else valeur.value
