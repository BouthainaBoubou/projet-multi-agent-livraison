import threading
import time
from dataclasses import dataclass, field

from fastapi import Depends, FastAPI, HTTPException, Request, status
from fastapi.middleware.cors import CORSMiddleware
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from src.agents.coordinator_agent import CommandesIncompletes, CoordinatorAgent
from src.api.schemas import (
    DemandeConnexion, DemandeCriteres, DemandeHeureDepart, DemandeIncident,
    EvenementPublie, FeuilleDeRoute, PlanPublie, Rejet, ReponseConnexion,
    TourneePubliee,
)
from src.data.loader import charger_comptes, charger_tout
from src.models.commande import (
    CRITERES_CLASSIFICATION, StatutCommande, valeurs_possibles,
)
from src.securite.authentification import (
    DROITS, DUREE_SESSION_MIN, AccesRefuse, EchecAuthentification, Permission,
    ServiceAuthentification, Session, SessionInvalide,
)

# Origines autorisées à appeler l'API depuis un navigateur. Volontairement
# limitées au poste local : `*` ouvrirait l'API à n'importe quelle page
# web ouverte par l'utilisateur. À élargir le jour d'un déploiement, pas
# avant.
ORIGINES_AUTORISEES = [
    "http://localhost:5173", "http://127.0.0.1:5173",   # Vite
    "http://localhost:3000", "http://127.0.0.1:3000",   # React
    "http://localhost:8000", "http://127.0.0.1:8000",
]

verrou_ecriture = threading.Lock()
securite = HTTPBearer(auto_error=False, description="Jeton reçu à la connexion")


@dataclass
class Etat:
    """Ce que le serveur garde entre deux requêtes."""

    coordinateur: CoordinatorAgent
    auth: ServiceAuthentification
    heure_depart: int | None = field(default=None)


# --- Accès à l'état et aux droits ---

def etat_de(requete: Request) -> Etat:
    return requete.app.state.etat


def jeton_de(justificatif: HTTPAuthorizationCredentials | None) -> str:
    if justificatif is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Aucun jeton présenté : se connecter d'abord",
            headers={"WWW-Authenticate": "Bearer"},
        )
    return justificatif.credentials


def exige(permission: Permission):
    """Fabrique une dépendance qui vérifie la session **et** le droit.

    Une fabrique plutôt qu'une fonction par permission : la règle est
    écrite une fois, et chaque adresse déclare simplement ce qu'elle
    exige. Une adresse qui oublierait de la déclarer n'aurait aucune
    protection — c'est pourquoi il n'y en a aucune sans.
    """

    def dependance(
        requete: Request,
        justificatif: HTTPAuthorizationCredentials | None = Depends(securite),
    ) -> Session:
        try:
            return etat_de(requete).auth.exiger(jeton_de(justificatif), permission)
        except SessionInvalide as expiree:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail=str(expiree),
                headers={"WWW-Authenticate": "Bearer"},
            ) from expiree
        except AccesRefuse as refus:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN, detail=str(refus)
            ) from refus

    return dependance


def session_simple(
    requete: Request,
    justificatif: HTTPAuthorizationCredentials | None = Depends(securite),
) -> Session:
    """Session valable, sans exigence de droit particulier."""
    try:
        return etat_de(requete).auth.session_de(jeton_de(justificatif))
    except SessionInvalide as expiree:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail=str(expiree),
            headers={"WWW-Authenticate": "Bearer"},
        ) from expiree


# --- Mise en forme des réponses ---

def _publier_plan(etat: Etat, session: Session) -> PlanPublie:
    coordinateur = etat.coordinateur
    if coordinateur.plan is None:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Aucun plan calculé : appeler POST /planifier",
        )

    modeles = {v.id: v.modele for v in coordinateur.donnees.vehicules}
    tournees = [
        TourneePubliee(
            vehicule=tournee.vehicule_id,
            modele=modeles.get(tournee.vehicule_id, ""),
            arrets=list(tournee.arrets),
            itineraire=coordinateur.itineraire(tournee),
            commandes=[
                coordinateur.order.vue(identifiant, session.role.value)
                for identifiant in tournee.commandes
            ],
            distance_km=tournee.distance_km,
            duree_min=tournee.duree_min,
            conduite_min=tournee.conduite_min,
            jours=tournee.jours,
            charge_kg=tournee.charge_kg,
            retard_pondere=tournee.retard_pondere,
            risque_fragilite=tournee.risque_fragilite,
        )
        for tournee in sorted(coordinateur.plan.tournees, key=lambda t: t.vehicule_id)
    ]
    return PlanPublie(
        score=coordinateur.score(),
        tournees=tournees,
        rejets=[
            Rejet(commande=rejet.commande_id, motif=rejet.motif)
            for rejet in coordinateur.plan.rejets
        ],
        heure_depart=etat.heure_depart,
        commandes_a_completer=coordinateur.commandes_a_completer(),
    )


def _erreur_de_classement(manquants: dict[str, list[str]]) -> HTTPException:
    """Traduit un refus de planifier en réponse exploitable par l'interface.

    409 et non 400 : la requête était correcte, c'est l'état du système
    qui l'empêche. Et la réponse dit **quoi saisir**, pour que l'écran
    puisse ouvrir le formulaire au lieu d'afficher un échec.
    """
    return HTTPException(
        status_code=status.HTTP_409_CONFLICT,
        detail={
            "message": (
                f"{len(manquants)} commande(s) non classée(s) : la "
                f"planification est impossible tant qu'un critère manque"
            ),
            "commandes_a_completer": manquants,
            "valeurs_possibles": {
                critere: valeurs_possibles(critere)
                for critere in CRITERES_CLASSIFICATION
            },
        },
    )


# --- Construction de l'application ---

def construire_application(
    dossier_donnees: str = "data",
    fichier_comptes: str = "data/utilisateurs.csv",
    horloge=time.time,
) -> FastAPI:
    """Assemble une application autonome.

    Les chemins et l'horloge sont des paramètres : c'est ce qui permet à
    `verif_api.py` de monter une application neuve à chaque test, sans
    serveur et sans réseau.
    """
    application = FastAPI(
        title="Système multi-agents de livraison",
        description=(
            "Optimisation dynamique des tournées nationales et "
            "internationales. Toutes les adresses sauf /connexion exigent "
            "un jeton, obtenu par POST /connexion."
        ),
        version="1.0.0",
    )
    application.add_middleware(
        CORSMiddleware,
        allow_origins=ORIGINES_AUTORISEES,
        allow_credentials=False,   # on utilise un jeton, pas un cookie
        allow_methods=["GET", "POST"],
        allow_headers=["Authorization", "Content-Type"],
    )
    application.state.etat = Etat(
        coordinateur=CoordinatorAgent(charger_tout(dossier_donnees)),
        auth=ServiceAuthentification(charger_comptes(fichier_comptes), horloge),
    )

    # ------------------------------------------------------------------
    # Connexion
    # ------------------------------------------------------------------

    @application.post("/connexion", response_model=ReponseConnexion, tags=["Accès"])
    def connexion(demande: DemandeConnexion, requete: Request) -> ReponseConnexion:
        """Ouvre une session et rend un jeton.

        Seule adresse accessible sans jeton. Un refus est toujours le
        même, quel que soit le motif : dire « identifiant inconnu »
        apprendrait quels comptes existent.
        """
        try:
            session = etat_de(requete).auth.connecter(
                demande.identifiant, demande.mot_de_passe
            )
        except EchecAuthentification as refus:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail=str(refus),
                headers={"WWW-Authenticate": "Bearer"},
            ) from refus
        return ReponseConnexion(
            jeton=session.jeton,
            identifiant=session.identifiant,
            role=session.role.value,
            vehicule=session.vehicule,
            expire_dans_min=DUREE_SESSION_MIN,
        )

    @application.post(
        "/deconnexion",
        status_code=status.HTTP_204_NO_CONTENT,
        tags=["Accès"],
    )
    def deconnexion(
        requete: Request,
        justificatif: HTTPAuthorizationCredentials | None = Depends(securite),
    ) -> None:
        """Révoque le jeton immédiatement.

        Ne se plaint pas d'un jeton déjà invalide : se déconnecter deux
        fois doit rester sans conséquence.
        """
        if justificatif is not None:
            etat_de(requete).auth.deconnecter(justificatif.credentials)

    @application.get("/moi", tags=["Accès"])
    def moi(session: Session = Depends(session_simple)) -> dict:
        """Qui suis-je, et qu'ai-je le droit de faire ?

        L'interface s'en sert pour n'afficher que les boutons utiles.
        Ce n'est qu'un confort d'affichage : les droits restent vérifiés
        à chaque requête, côté serveur.
        """
        return {
            "identifiant": session.identifiant,
            "role": session.role.value,
            "vehicule": session.vehicule,
            "droits": sorted(droit.value for droit in DROITS[session.role]),
        }

    # ------------------------------------------------------------------
    # Plan
    # ------------------------------------------------------------------

    @application.get("/plan", response_model=PlanPublie, tags=["Plan"])
    def lire_plan(
        requete: Request,
        session: Session = Depends(exige(Permission.VOIR_PLAN)),
    ) -> PlanPublie:
        """Le plan courant, sans rien recalculer."""
        return _publier_plan(etat_de(requete), session)

    @application.post("/planifier", response_model=PlanPublie, tags=["Plan"])
    def planifier(
        requete: Request,
        session: Session = Depends(exige(Permission.PLANIFIER)),
    ) -> PlanPublie:
        """Recalcule le plan complet.

        Refuse tant qu'une commande n'est pas classée, et dit laquelle.
        """
        etat = etat_de(requete)
        with verrou_ecriture:
            try:
                etat.coordinateur.planifier(
                    f"planification demandée par {session.identifiant}"
                )
            except CommandesIncompletes as refus:
                raise _erreur_de_classement(refus.manquants) from refus
            return _publier_plan(etat, session)

    @application.post("/heure-depart", response_model=PlanPublie, tags=["Plan"])
    def heure_depart(
        demande: DemandeHeureDepart,
        requete: Request,
        session: Session = Depends(exige(Permission.PLANIFIER)),
    ) -> PlanPublie:
        """Règle le réseau sur la circulation d'une heure donnée.

        Le trafic n'est pas une valeur qu'on déclare : il découle de
        l'heure à laquelle on décide de partir. Replanifie si un plan
        existe déjà.
        """
        etat = etat_de(requete)
        with verrou_ecriture:
            try:
                etat.coordinateur.definir_heure_depart(demande.heure)
            except CommandesIncompletes as refus:
                raise _erreur_de_classement(refus.manquants) from refus
            etat.heure_depart = demande.heure
            if etat.coordinateur.plan is None:
                etat.coordinateur.planifier("premier plan après réglage de l'heure")
            return _publier_plan(etat, session)

    # ------------------------------------------------------------------
    # Classement des commandes
    # ------------------------------------------------------------------

    @application.get("/commandes/a-completer", tags=["Commandes"])
    def a_completer(
        requete: Request,
        session: Session = Depends(exige(Permission.CLASSER_COMMANDE)),
    ) -> dict:
        """Ce que le dispatcheur doit saisir avant toute planification.

        Renvoie aussi les valeurs acceptées : l'écran de saisie construit
        ses listes déroulantes à partir d'ici, jamais d'une liste
        recopiée à la main dans le frontend.
        """
        coordinateur = etat_de(requete).coordinateur
        return {
            "commandes": coordinateur.commandes_a_completer(),
            "valeurs_possibles": {
                critere: valeurs_possibles(critere)
                for critere in CRITERES_CLASSIFICATION
            },
        }

    @application.post("/commandes/{id_commande}/criteres", tags=["Commandes"])
    def classer(
        id_commande: str,
        demande: DemandeCriteres,
        requete: Request,
        session: Session = Depends(exige(Permission.CLASSER_COMMANDE)),
    ) -> dict:
        """Saisit ou corrige les critères d'une commande.

        Une seule adresse pour les deux gestes : compléter une commande
        qui arrive sans critères, et la reclasser quand le client change
        d'avis. Du point de vue de l'écran c'est le même formulaire ; le
        domaine, lui, applique des règles différentes — on ne reclasse
        pas une marchandise déjà partie.

        Le journal retient **qui** a saisi : la traçabilité n'est pas une
        option quand on manipule des données confidentielles.
        """
        etat = etat_de(requete)
        criteres = demande.model_dump(exclude_none=True)
        if not criteres:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Aucun critère fourni",
            )

        with verrou_ecriture:
            commande = etat.coordinateur.order.trouver_commande_par_id(id_commande)
            if commande is None:
                raise HTTPException(
                    status_code=status.HTTP_404_NOT_FOUND,
                    detail=f"Commande inconnue : {id_commande}",
                )
            incomplete = commande.statut is StatutCommande.INCOMPLETE
            try:
                if incomplete:
                    etat.coordinateur.completer_commande(
                        id_commande, auteur=session.identifiant, **criteres
                    )
                else:
                    etat.coordinateur.modifier_commande(
                        id_commande, auteur=session.identifiant, **criteres
                    )
            except CommandesIncompletes as refus:
                raise _erreur_de_classement(refus.manquants) from refus
            except ValueError as invalide:
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST, detail=str(invalide)
                ) from invalide

            return {
                "commande": etat.coordinateur.order.vue(id_commande, "dispatcheur"),
                "geste": "saisie" if incomplete else "modification",
                "commandes_a_completer": etat.coordinateur.commandes_a_completer(),
            }

    # ------------------------------------------------------------------
    # Incidents
    # ------------------------------------------------------------------

    @application.post("/incident", response_model=PlanPublie, tags=["Incidents"])
    def incident(
        demande: DemandeIncident,
        requete: Request,
        session: Session = Depends(exige(Permission.DECLARER_INCIDENT)),
    ) -> PlanPublie:
        """Déclare un événement, replanifie, et mesure l'écart de Z.

        Les paramètres attendus dépendent du type ; ce qui manque produit
        un 400 explicite plutôt qu'une erreur du domaine.
        """
        etat = etat_de(requete)
        coordinateur = etat.coordinateur

        def exiger(*champs: str) -> None:
            absents = [champ for champ in champs if getattr(demande, champ) is None]
            if absents:
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail=(
                        f"Incident « {demande.type} » : champ(s) manquant(s) "
                        f"{absents}"
                    ),
                )

        with verrou_ecriture:
            try:
                if demande.type in ("panne", "reparation"):
                    exiger("vehicule")
                    if demande.type == "panne":
                        coordinateur.declarer_panne(demande.vehicule)
                    else:
                        coordinateur.declarer_reparation(demande.vehicule)
                elif demande.type in ("blocage", "deblocage"):
                    exiger("origine", "destination")
                    if demande.type == "blocage":
                        coordinateur.declarer_blocage(
                            demande.origine, demande.destination
                        )
                    else:
                        coordinateur.declarer_deblocage(
                            demande.origine, demande.destination
                        )
                elif demande.type == "congestion":
                    exiger("origine", "destination", "niveau")
                    coordinateur.declarer_congestion(
                        demande.origine, demande.destination, demande.niveau
                    )
                else:
                    exiger("origine", "destination", "duree_min")
                    coordinateur.declarer_attente_frontiere(
                        demande.origine, demande.destination, demande.duree_min
                    )
            except CommandesIncompletes as refus:
                raise _erreur_de_classement(refus.manquants) from refus
            except ValueError as invalide:
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST, detail=str(invalide)
                ) from invalide
            return _publier_plan(etat, session)

    # ------------------------------------------------------------------
    # Mission d'un véhicule
    # ------------------------------------------------------------------

    @application.get(
        "/tournee/{id_vehicule}", response_model=FeuilleDeRoute, tags=["Mission"]
    )
    def tournee(
        id_vehicule: str,
        requete: Request,
        justificatif: HTTPAuthorizationCredentials | None = Depends(securite),
    ) -> FeuilleDeRoute:
        """La feuille de route d'un véhicule, filtrée selon le demandeur.

        **Aucun paramètre `role` n'est accepté.** Le rôle est lu dans la
        session, et un conducteur authentifié se voit refuser la mission
        d'un collègue : le compte porte son véhicule.

        Le contenu est filtré par `Commande.vue(role)` — le même filtre
        que la carte du chauffeur. Une commande sensible n'apparaît que
        par son identifiant.
        """
        etat = etat_de(requete)
        try:
            session = etat.auth.exiger_acces_tournee(
                jeton_de(justificatif), id_vehicule
            )
        except SessionInvalide as expiree:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail=str(expiree),
                headers={"WWW-Authenticate": "Bearer"},
            ) from expiree
        except AccesRefuse as refus:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN, detail=str(refus)
            ) from refus

        if etat.coordinateur.plan is None:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="Aucun plan calculé : le dispatcheur doit planifier",
            )
        try:
            feuille = etat.coordinateur.feuille_de_route(
                id_vehicule, session.role.value
            )
        except ValueError as absente:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND, detail=str(absente)
            ) from absente

        modeles = {v.id: v.modele for v in etat.coordinateur.donnees.vehicules}
        tournee_choisie = next(
            t for t in etat.coordinateur.plan.tournees if t.vehicule_id == id_vehicule
        )
        return FeuilleDeRoute(
            vehicule=id_vehicule,
            modele=modeles.get(id_vehicule, ""),
            arrets=feuille["arrets"],
            itineraire=etat.coordinateur.itineraire(tournee_choisie),
            commandes=feuille["commandes"],
        )

    # ------------------------------------------------------------------
    # Journal
    # ------------------------------------------------------------------

    @application.get(
        "/journal", response_model=list[EvenementPublie], tags=["Journal"]
    )
    def journal(
        requete: Request,
        session: Session = Depends(exige(Permission.VOIR_JOURNAL)),
    ) -> list[EvenementPublie]:
        """L'historique des décisions, avec l'écart de Z de chacune.

        C'est la pièce qui rend le système défendable : sans comparaison
        chiffrée avant/après, « le système réagit » n'est qu'une
        affirmation.
        """
        return [
            EvenementPublie(
                numero=evenement.numero,
                type=evenement.type,
                description=evenement.description,
                z_avant=evenement.z_avant,
                z_apres=evenement.z_apres,
                variation=evenement.variation,
                auteur=evenement.auteur,
            )
            for evenement in etat_de(requete).coordinateur.journal
        ]

    @application.get("/journal/connexions", tags=["Journal"])
    def journal_connexions(
        requete: Request,
        session: Session = Depends(exige(Permission.VOIR_JOURNAL)),
    ) -> list[dict]:
        """Qui s'est connecté, quand, avec quel résultat.

        Exigé par la protection des données : il faut pouvoir répondre à
        « qui a consulté quoi ». Ne contient aucun mot de passe, même
        erroné.
        """
        return [
            {
                "numero": acces.numero,
                "identifiant": acces.identifiant,
                "succes": acces.succes,
                "motif": acces.motif,
            }
            for acces in etat_de(requete).auth.journal
        ]

    return application


app = construire_application()
