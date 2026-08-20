"""Authentification et contrôle d'accès.

Le système n'a que **deux types d'utilisateurs**, et ils ne voient pas la
même chose :

- le **dispatcheur** décide : il planifie, déclare les incidents, classe
  les commandes, consulte tout ;
- le **conducteur** exécute : il consulte **sa** mission, et rien d'autre.

Trois principes gouvernent ce module.

**1. Le rôle vient du compte, jamais de la demande.** Tant que le rôle
était un paramètre (`?role=conducteur`), n'importe qui pouvait écrire
`?role=dispatcheur`. Le masquage des commandes sensibles ne protégeait
alors plus rien : la porte était fermée et la clé scotchée dessus. Ici,
le rôle est lu dans le compte au moment de la connexion et le demandeur
ne peut plus le choisir.

**2. Le moindre privilège.** Un conducteur ne voit pas *les* tournées, il
voit *la sienne*. Le rôle seul ne suffit pas : le compte porte aussi le
véhicule, et l'accès est refusé même à un conducteur authentifié qui
demande la feuille de route d'un collègue.

**3. Aucun mot de passe n'est stocké, ni journalisé, ni comparé en
clair.** Le fichier ne contient que des empreintes, calculées avec un
algorithme volontairement lent (PBKDF2-HMAC-SHA256, 600 000 itérations,
recommandation OWASP). Une empreinte volée ne se retourne pas en mot de
passe en un temps utile.

Ce qui reste **hors périmètre**, et doit être écrit dans le rapport :
HTTPS (sans lui, un jeton circule en clair sur le réseau — c'est
indispensable en production, pas dans une démonstration locale),
récupération de mot de passe par courriel, double facteur, et base de
données d'utilisateurs. Le fichier CSV joue ce rôle ici.
"""

import hashlib
import hmac
import secrets
import time
from dataclasses import dataclass, field
from enum import Enum

# --- Paramètres de sécurité, réunis ici pour être discutables ---

ALGORITHME = "pbkdf2_sha256"
# 600 000 itérations : recommandation OWASP pour PBKDF2-HMAC-SHA256. Le
# but est que vérifier un mot de passe coûte quelques centaines de
# millisecondes — insensible pour un humain qui se connecte une fois,
# ruineux pour qui essaierait des millions de combinaisons.
ITERATIONS = 600_000
TAILLE_SEL = 16          # octets de sel aléatoire, propre à chaque compte

DUREE_SESSION_MIN = 480.0        # 8 h : une journée de travail
INACTIVITE_MAX_MIN = 30.0        # 30 min sans activité et la session tombe
TENTATIVES_MAX = 5               # avant verrouillage temporaire
VERROU_MIN = 15.0                # durée du verrouillage

LONGUEUR_MIN_MOT_DE_PASSE = 12


class Role(Enum):
    """Les deux seuls rôles du système."""
    DISPATCHEUR = "dispatcheur"
    CONDUCTEUR = "conducteur"


class Permission(Enum):
    """Ce qu'on a le droit de faire, indépendamment de qui on est.

    Nommer les permissions plutôt que tester le rôle partout : le jour
    où un troisième rôle apparaît, on modifie une table, pas vingt `if`.
    """
    VOIR_PLAN = "voir_plan"
    PLANIFIER = "planifier"
    DECLARER_INCIDENT = "declarer_incident"
    CLASSER_COMMANDE = "classer_commande"
    VOIR_JOURNAL = "voir_journal"
    VOIR_TOUTES_TOURNEES = "voir_toutes_tournees"
    VOIR_SA_TOURNEE = "voir_sa_tournee"
    DECLARER_LIVRAISON = "declarer_livraison"


# La table des droits. Elle se lit d'un coup d'œil, et c'est le but :
# une règle de sécurité qu'on ne peut pas lire est une règle qu'on ne
# peut pas vérifier.
DROITS: dict[Role, frozenset[Permission]] = {
    Role.DISPATCHEUR: frozenset({
        Permission.VOIR_PLAN,
        Permission.PLANIFIER,
        Permission.DECLARER_INCIDENT,
        Permission.CLASSER_COMMANDE,
        Permission.VOIR_JOURNAL,
        Permission.VOIR_TOUTES_TOURNEES,
        Permission.VOIR_SA_TOURNEE,
        Permission.DECLARER_LIVRAISON,
    }),
    Role.CONDUCTEUR: frozenset({
        Permission.VOIR_SA_TOURNEE,
        Permission.DECLARER_LIVRAISON,
    }),
}


class EchecAuthentification(Exception):
    """Connexion refusée.

    Le message ne dit jamais *ce qui* a échoué. « Identifiant inconnu »
    apprendrait à un attaquant quels comptes existent : il lui suffirait
    de faire défiler des identifiants pour dresser la liste du personnel.
    Un seul message pour les deux cas.
    """


class SessionInvalide(Exception):
    """Jeton absent, inconnu, expiré ou révoqué."""


class AccesRefuse(Exception):
    """Session valable, mais le rôle n'a pas ce droit."""


@dataclass
class Compte:
    """Un utilisateur du système.

    Ne contient **aucune donnée personnelle** au-delà de ce que la
    fonction exige : pas de nom, pas de courriel, pas de téléphone.
    C'est le principe de minimisation : la donnée qu'on ne collecte pas
    est celle qu'on ne peut ni perdre ni divulguer.
    """

    identifiant: str
    role: Role
    sel: bytes
    empreinte: bytes
    # Véhicule confié au conducteur. Vide pour un dispatcheur, qui n'est
    # rattaché à aucun véhicule en particulier.
    vehicule: str = ""
    algorithme: str = ALGORITHME
    iterations: int = ITERATIONS
    actif: bool = True

    def __post_init__(self) -> None:
        if not self.identifiant:
            raise ValueError("Compte : identifiant vide")
        if self.algorithme != ALGORITHME:
            raise ValueError(
                f"Compte {self.identifiant} : algorithme '{self.algorithme}' "
                f"non pris en charge (attendu '{ALGORITHME}')"
            )
        if self.iterations < 100_000:
            raise ValueError(
                f"Compte {self.identifiant} : {self.iterations} itérations, "
                f"c'est trop peu pour résister à une attaque hors ligne"
            )
        if self.role is Role.CONDUCTEUR and not self.vehicule:
            raise ValueError(
                f"Compte {self.identifiant} : un conducteur doit être "
                f"rattaché à un véhicule, sinon il ne peut voir aucune "
                f"mission — ou pire, toutes"
            )
        if self.role is Role.DISPATCHEUR and self.vehicule:
            raise ValueError(
                f"Compte {self.identifiant} : un dispatcheur n'est rattaché "
                f"à aucun véhicule (reçu : '{self.vehicule}')"
            )


@dataclass
class Session:
    """Une connexion ouverte.

    Le jeton est **opaque** : une simple suite de caractères aléatoires,
    sans information à l'intérieur. Un jeton signé de type JWT porterait
    le rôle dans son contenu et ne pourrait pas être révoqué avant son
    expiration ; celui-ci vit dans le service, donc une déconnexion le
    supprime pour de bon.
    """

    jeton: str
    identifiant: str
    role: Role
    vehicule: str
    ouverte_a: float
    derniere_activite: float


@dataclass
class Acces:
    """Une ligne du journal des connexions.

    Obligatoire pour pouvoir répondre à « qui a consulté cette commande,
    et quand ». Ne contient jamais de mot de passe, même erroné : un
    utilisateur qui se trompe de champ écrirait son mot de passe dans son
    identifiant, et le journal le conserverait en clair.
    """

    numero: int
    identifiant: str
    succes: bool
    motif: str = ""


def verifier_solidite(mot_de_passe: str, identifiant: str = "") -> None:
    """Refuse un mot de passe trop faible, avant même de le hacher.

    Trois règles seulement, mais celles qui comptent : une longueur
    suffisante — c'est de très loin le facteur le plus efficace —, un peu
    de variété, et l'interdiction de reprendre l'identifiant.
    """
    if len(mot_de_passe) < LONGUEUR_MIN_MOT_DE_PASSE:
        raise ValueError(
            f"Mot de passe trop court : {len(mot_de_passe)} caractères, "
            f"minimum {LONGUEUR_MIN_MOT_DE_PASSE}"
        )
    if mot_de_passe.isalpha() or mot_de_passe.isdigit():
        raise ValueError(
            "Mot de passe trop uniforme : mélanger lettres, chiffres et "
            "au moins un autre caractère"
        )
    if identifiant and identifiant.lower() in mot_de_passe.lower():
        raise ValueError(
            "Mot de passe interdit : il contient l'identifiant du compte"
        )


def calculer_empreinte(
    mot_de_passe: str, sel: bytes, iterations: int = ITERATIONS
) -> bytes:
    """Transforme un mot de passe en empreinte, avec son sel.

    Le **sel** est une valeur aléatoire propre à chaque compte. Sans lui,
    deux personnes ayant choisi le même mot de passe auraient la même
    empreinte, et une table précalculée les casserait toutes les deux
    d'un coup.
    """
    return hashlib.pbkdf2_hmac(
        "sha256", mot_de_passe.encode("utf-8"), sel, iterations
    )


def creer_compte(
    identifiant: str,
    mot_de_passe: str,
    role: Role,
    vehicule: str = "",
) -> Compte:
    """Fabrique un compte à partir d'un mot de passe en clair.

    C'est le seul endroit où un mot de passe en clair entre dans le
    système, et il n'en ressort pas : seule l'empreinte est conservée.
    """
    verifier_solidite(mot_de_passe, identifiant)
    sel = secrets.token_bytes(TAILLE_SEL)
    return Compte(
        identifiant=identifiant,
        role=role,
        sel=sel,
        empreinte=calculer_empreinte(mot_de_passe, sel),
        vehicule=vehicule,
    )


class ServiceAuthentification:
    """Ouvre, vérifie et ferme les sessions ; dit qui a le droit de quoi.

    L'horloge est un paramètre. Cela paraît inutile jusqu'au moment
    d'écrire un test : sans elle, vérifier qu'une session expire au bout
    de huit heures demanderait d'attendre huit heures.
    """

    def __init__(self, comptes: list[Compte], horloge=time.time) -> None:
        self.comptes = {compte.identifiant: compte for compte in comptes}
        self.horloge = horloge
        self.sessions: dict[str, Session] = {}
        self.journal: list[Acces] = []
        # Compteur d'échecs et heure de fin de verrouillage, par compte.
        self._echecs: dict[str, int] = {}
        self._verrous: dict[str, float] = {}

    # --- Connexion ---

    def connecter(self, identifiant: str, mot_de_passe: str) -> Session:
        """Ouvre une session, ou refuse sans dire pourquoi."""
        maintenant = self.horloge()

        fin_verrou = self._verrous.get(identifiant)
        if fin_verrou is not None and maintenant < fin_verrou:
            reste = (fin_verrou - maintenant) / 60
            self._inscrire(identifiant, False, "compte temporairement verrouillé")
            raise EchecAuthentification(
                f"Compte temporairement verrouillé après "
                f"{TENTATIVES_MAX} tentatives. Réessayer dans "
                f"{reste:.0f} minute(s)."
            )

        compte = self.comptes.get(identifiant)

        # Même sur un identifiant inconnu, on calcule une empreinte
        # factice. Sans cela, un refus immédiat contre un refus lent
        # révélerait quels comptes existent — la durée de la réponse est
        # une information comme une autre.
        if compte is None or not compte.actif:
            calculer_empreinte(mot_de_passe, b"sel-factice-constant", ITERATIONS)
            self._compter_echec(identifiant, maintenant)
            self._inscrire(identifiant, False, "identifiant ou mot de passe")
            raise EchecAuthentification("Identifiant ou mot de passe incorrect")

        candidate = calculer_empreinte(mot_de_passe, compte.sel, compte.iterations)
        # Comparaison à temps constant : une comparaison ordinaire
        # s'arrête au premier octet différent, et cette durée trahit le
        # nombre d'octets déjà justes.
        if not hmac.compare_digest(candidate, compte.empreinte):
            self._compter_echec(identifiant, maintenant)
            self._inscrire(identifiant, False, "identifiant ou mot de passe")
            raise EchecAuthentification("Identifiant ou mot de passe incorrect")

        self._echecs.pop(identifiant, None)
        self._verrous.pop(identifiant, None)

        session = Session(
            jeton=secrets.token_urlsafe(32),
            identifiant=compte.identifiant,
            role=compte.role,
            vehicule=compte.vehicule,
            ouverte_a=maintenant,
            derniere_activite=maintenant,
        )
        self.sessions[session.jeton] = session
        self._inscrire(identifiant, True, f"connexion {compte.role.value}")
        return session

    def deconnecter(self, jeton: str) -> None:
        """Ferme une session. Le jeton devient inutilisable immédiatement."""
        session = self.sessions.pop(jeton, None)
        if session is not None:
            self._inscrire(session.identifiant, True, "déconnexion")

    # --- Vérification ---

    def session_de(self, jeton: str) -> Session:
        """Retrouve une session valable, ou refuse.

        Deux expirations, pas une : une **durée de vie absolue**, pour
        qu'un jeton oublié ne serve pas éternellement, et une **durée
        d'inactivité**, pour qu'un poste laissé sans surveillance se
        referme tout seul.
        """
        session = self.sessions.get(jeton)
        if session is None:
            raise SessionInvalide("Session inconnue : se reconnecter")

        maintenant = self.horloge()
        age = (maintenant - session.ouverte_a) / 60
        inactivite = (maintenant - session.derniere_activite) / 60

        if age > DUREE_SESSION_MIN:
            self.sessions.pop(jeton, None)
            raise SessionInvalide(
                f"Session expirée après {DUREE_SESSION_MIN / 60:.0f} h : "
                f"se reconnecter"
            )
        if inactivite > INACTIVITE_MAX_MIN:
            self.sessions.pop(jeton, None)
            raise SessionInvalide(
                f"Session fermée après {INACTIVITE_MAX_MIN:.0f} min "
                f"d'inactivité : se reconnecter"
            )

        session.derniere_activite = maintenant
        return session

    def exiger(self, jeton: str, permission: Permission) -> Session:
        """Vérifie la session **et** le droit. Rend la session si tout va bien.

        Une seule fonction pour les deux contrôles : les séparer
        laisserait un jour quelqu'un vérifier l'un et oublier l'autre.
        """
        session = self.session_de(jeton)
        if permission not in DROITS[session.role]:
            raise AccesRefuse(
                f"Le rôle « {session.role.value} » n'a pas le droit "
                f"« {permission.value} »"
            )
        return session

    def exiger_acces_tournee(self, jeton: str, id_vehicule: str) -> Session:
        """Contrôle d'accès à la feuille de route d'un véhicule.

        Le rôle ne suffit pas ici, et c'est tout l'intérêt : un
        conducteur authentifié reste refusé sur la mission d'un collègue.
        Sans cette règle, « conducteur » serait un passe-partout et la
        confidentialité ne tiendrait qu'à la bonne volonté de chacun.
        """
        session = self.session_de(jeton)
        if Permission.VOIR_TOUTES_TOURNEES in DROITS[session.role]:
            return session
        if session.vehicule != id_vehicule:
            raise AccesRefuse(
                f"Le conducteur {session.identifiant} est rattaché au "
                f"véhicule {session.vehicule} : la mission de {id_vehicule} "
                f"ne le concerne pas"
            )
        return session

    # --- Restitution ---

    def journal_texte(self) -> str:
        """Vue texte du journal des connexions."""
        return "\n".join(
            f"{acces.numero:>3}. {'OK   ' if acces.succes else 'REFUS'} "
            f"{acces.identifiant:<16} {acces.motif}"
            for acces in self.journal
        )

    # --- Interne ---

    def _compter_echec(self, identifiant: str, maintenant: float) -> None:
        """Compte un échec et verrouille au bout de `TENTATIVES_MAX`.

        Le verrouillage bloque l'essai systématique de mots de passe.
        Il a un revers connu : qui devine un identifiant peut gêner son
        titulaire un quart d'heure. C'est le compromis habituel, et il
        penche du bon côté quand les comptes sont peu nombreux et
        internes.
        """
        self._echecs[identifiant] = self._echecs.get(identifiant, 0) + 1
        if self._echecs[identifiant] >= TENTATIVES_MAX:
            self._verrous[identifiant] = maintenant + VERROU_MIN * 60
            self._echecs[identifiant] = 0

    def _inscrire(self, identifiant: str, succes: bool, motif: str) -> None:
        self.journal.append(
            Acces(
                numero=len(self.journal) + 1,
                identifiant=identifiant,
                succes=succes,
                motif=motif,
            )
        )
