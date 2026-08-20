"""Contrôle de l'authentification et du contrôle d'accès.

Même esprit que `verif_criteres.py` : une liste de critères, chacun vrai
ou faux. Les tests de durée n'attendent pas : l'horloge du service est
un paramètre, on la fait avancer à la main.

    python verif_securite.py
"""

from src.agents.coordinator_agent import CoordinatorAgent
from src.data.loader import charger_comptes, charger_tout
from src.securite.authentification import (
    DUREE_SESSION_MIN, INACTIVITE_MAX_MIN, TENTATIVES_MAX,
    AccesRefuse, EchecAuthentification, Permission, Role,
    ServiceAuthentification, SessionInvalide, calculer_empreinte,
    creer_compte, verifier_solidite,
)

DISPATCHEUR = ("dispatch", "Tournees#2026!MA")
CHAUFFEUR_V001 = ("chauffeur.v001", "Conduite#2026-V001")
CHAUFFEUR_V005 = ("chauffeur.v005", "Conduite#2026-V005")

resultats: list[tuple[str, bool, str]] = []


def verifier(libelle: str, condition: bool, detail: str = "") -> None:
    resultats.append((libelle, bool(condition), detail))


class Horloge:
    """Une horloge qu'on fait avancer soi-même, en minutes."""

    def __init__(self) -> None:
        self.instant = 1_000_000.0

    def __call__(self) -> float:
        return self.instant

    def avancer(self, minutes: float) -> None:
        self.instant += minutes * 60


def service(horloge=None) -> ServiceAuthentification:
    comptes = charger_comptes("data/utilisateurs.csv")
    return ServiceAuthentification(comptes, horloge or (lambda: 1_000_000.0))


# =====================================================================
# 1. Les mots de passe ne sont jamais stockés en clair
# =====================================================================

contenu = open("data/utilisateurs.csv", encoding="utf-8").read()
verifier(
    "01 · aucun mot de passe dans le fichier des comptes",
    all(mot not in contenu for _, mot in
        (DISPATCHEUR, CHAUFFEUR_V001, CHAUFFEUR_V005)),
)
verifier(
    "02 · le fichier ne contient que des empreintes salées",
    "pbkdf2_sha256" in contenu and "600000" in contenu,
)

comptes = charger_comptes("data/utilisateurs.csv")
sels = [compte.sel for compte in comptes]
verifier(
    "03 · chaque compte a son propre sel",
    len(set(sels)) == len(sels),
    f"{len(sels)} comptes, {len(set(sels))} sels distincts",
)

a = creer_compte("essai.a", "MemeMotDePasse#1", Role.DISPATCHEUR)
b = creer_compte("essai.b", "MemeMotDePasse#1", Role.DISPATCHEUR)
verifier(
    "04 · deux comptes, même mot de passe, empreintes différentes",
    a.empreinte != b.empreinte,
    "c'est le sel qui l'empêche : une table précalculée ne casse pas les deux",
)
verifier(
    "05 · l'empreinte est reproductible pour un sel donné",
    calculer_empreinte("MemeMotDePasse#1", a.sel, a.iterations) == a.empreinte,
)

for faible, raison in (
    ("court#1", "trop court"),
    ("motdepasseabc", "que des lettres"),
    ("123456789012", "que des chiffres"),
    ("dispatch#2026", "contient l'identifiant"),
):
    try:
        verifier_solidite(faible, "dispatch")
        accepte = True
    except ValueError:
        accepte = False
    verifier(f"06 · mot de passe refusé — {raison}", not accepte)

# =====================================================================
# 2. Le rôle vient du compte, pas de la demande
# =====================================================================

auth = service()
session_d = auth.connecter(*DISPATCHEUR)
session_c = auth.connecter(*CHAUFFEUR_V001)

verifier(
    "07 · connexion valable, le rôle est lu dans le compte",
    session_d.role is Role.DISPATCHEUR and session_c.role is Role.CONDUCTEUR,
)
verifier(
    "08 · le conducteur est rattaché à son véhicule",
    session_c.vehicule == "V001",
)
verifier(
    "09 · le jeton est opaque : il ne contient ni rôle ni identifiant",
    "conducteur" not in session_c.jeton
    and "chauffeur" not in session_c.jeton
    and len(session_c.jeton) >= 32,
    f"exemple : {session_c.jeton[:12]}…",
)
verifier(
    "10 · deux connexions donnent deux jetons différents",
    auth.connecter(*DISPATCHEUR).jeton != session_d.jeton,
)

# =====================================================================
# 3. Une connexion refusée ne dit pas pourquoi
# =====================================================================

messages = []
for identifiant, mot in (
    ("dispatch", "MauvaisMotDePasse#9"),
    ("inconnu.total", "MauvaisMotDePasse#9"),
):
    try:
        service().connecter(identifiant, mot)
        messages.append("ACCEPTE")
    except EchecAuthentification as refus:
        messages.append(str(refus))

verifier("11 · un mauvais mot de passe est refusé", messages[0] != "ACCEPTE")
verifier("12 · un identifiant inconnu est refusé", messages[1] != "ACCEPTE")
verifier(
    "13 · les deux refus sont indiscernables",
    messages[0] == messages[1],
    f"« {messages[0]} » — sinon on pourrait dresser la liste des comptes",
)

auth = service()
for _ in range(TENTATIVES_MAX):
    try:
        auth.connecter("dispatch", "MauvaisMotDePasse#9")
    except EchecAuthentification:
        pass
try:
    auth.connecter(*DISPATCHEUR)
    verrouille, message = False, "le bon mot de passe est passé quand même"
except EchecAuthentification as refus:
    verrouille, message = "verrouillé" in str(refus), str(refus)
verifier(
    f"14 · verrouillage après {TENTATIVES_MAX} échecs", verrouille, message
)

verifier(
    "15 · aucun mot de passe dans le journal des connexions",
    "MauvaisMotDePasse#9" not in auth.journal_texte(),
)
verifier(
    "16 · le journal garde la trace des refus",
    sum(1 for acces in auth.journal if not acces.succes) >= TENTATIVES_MAX,
    f"{len(auth.journal)} ligne(s) journalisée(s)",
)

# =====================================================================
# 4. Les sessions expirent
# =====================================================================

horloge = Horloge()
auth = service(horloge)
jeton = auth.connecter(*DISPATCHEUR).jeton

horloge.avancer(INACTIVITE_MAX_MIN - 1)
verifier(
    "17 · une session active reste valable",
    auth.session_de(jeton).identifiant == "dispatch",
)

horloge.avancer(INACTIVITE_MAX_MIN + 1)
try:
    auth.session_de(jeton)
    ferme = False
except SessionInvalide:
    ferme = True
verifier(
    f"18 · session fermée après {INACTIVITE_MAX_MIN:.0f} min d'inactivité",
    ferme,
)

horloge = Horloge()
auth = service(horloge)
jeton = auth.connecter(*DISPATCHEUR).jeton
# On reste actif : une requête toutes les 10 minutes pendant 9 heures.
expire_a = None
for minute in range(10, 600, 10):
    horloge.avancer(10)
    try:
        auth.session_de(jeton)
    except SessionInvalide:
        expire_a = minute
        break
verifier(
    f"19 · session expirée au bout de {DUREE_SESSION_MIN / 60:.0f} h même en restant actif",
    expire_a is not None and expire_a > DUREE_SESSION_MIN,
    f"expirée à {expire_a} min d'ouverture",
)

auth = service()
jeton = auth.connecter(*DISPATCHEUR).jeton
auth.deconnecter(jeton)
try:
    auth.session_de(jeton)
    revoque = False
except SessionInvalide:
    revoque = True
verifier("20 · la déconnexion révoque le jeton immédiatement", revoque)

try:
    auth.session_de("jeton-invente-de-toutes-pieces")
    accepte = True
except SessionInvalide:
    accepte = False
verifier("21 · un jeton inventé n'ouvre rien", not accepte)

# =====================================================================
# 5. Le moindre privilège
# =====================================================================

auth = service()
jeton_d = auth.connecter(*DISPATCHEUR).jeton
jeton_c = auth.connecter(*CHAUFFEUR_V001).jeton

verifier(
    "22 · le dispatcheur peut planifier",
    auth.exiger(jeton_d, Permission.PLANIFIER).role is Role.DISPATCHEUR,
)
for permission in (Permission.PLANIFIER, Permission.DECLARER_INCIDENT,
                   Permission.CLASSER_COMMANDE, Permission.VOIR_JOURNAL):
    try:
        auth.exiger(jeton_c, permission)
        refuse = False
    except AccesRefuse:
        refuse = True
    verifier(f"23 · le conducteur ne peut pas « {permission.value} »", refuse)

verifier(
    "24 · le conducteur voit sa propre mission",
    auth.exiger_acces_tournee(jeton_c, "V001").vehicule == "V001",
)
try:
    auth.exiger_acces_tournee(jeton_c, "V003")
    refuse = False
except AccesRefuse:
    refuse = True
verifier(
    "25 · il ne voit pas la mission d'un collègue",
    refuse,
    "le rôle seul ne suffit pas : le véhicule du compte est vérifié",
)
verifier(
    "26 · le dispatcheur voit toutes les missions",
    auth.exiger_acces_tournee(jeton_d, "V003").role is Role.DISPATCHEUR,
)

# =====================================================================
# 6. Le lien avec le masquage des commandes sensibles
# =====================================================================

coordinateur = CoordinatorAgent(charger_tout("data"))
coordinateur.planifier()
auth = service()
jeton_c = auth.connecter(*CHAUFFEUR_V001).jeton
session = auth.exiger_acces_tournee(jeton_c, "V001")

feuille = coordinateur.feuille_de_route("V001", session.role.value)
sensibles = [vue for vue in feuille["commandes"] if vue.get("confidentiel")]
verifier(
    "27 · le rôle authentifié pilote le masquage",
    sensibles and all("poids" not in vue for vue in sensibles),
    f"{len(sensibles)} commande(s) masquée(s) sur la mission de V001",
)

feuille_dispatcheur = coordinateur.feuille_de_route("V001", "dispatcheur")
verifier(
    "28 · le dispatcheur, lui, voit le détail",
    all("poids" in vue for vue in feuille_dispatcheur["commandes"]),
)

# Le trou que l'authentification vient fermer : sans elle, le rôle était
# un paramètre que le demandeur choisissait lui-même.
verifier(
    "29 · un conducteur ne peut plus se déclarer dispatcheur",
    auth.session_de(jeton_c).role is Role.CONDUCTEUR,
    "le rôle est lu dans le compte, il n'est plus transmis par le client",
)

# =====================================================================
# 7. Le fichier des comptes reste cohérent
# =====================================================================

verifier(
    "30 · tout conducteur est rattaché à un véhicule",
    all(compte.vehicule for compte in comptes if compte.role is Role.CONDUCTEUR),
)
verifier(
    "31 · aucun dispatcheur n'est rattaché à un véhicule",
    all(not compte.vehicule for compte in comptes
        if compte.role is Role.DISPATCHEUR),
)
verifier(
    "32 · il existe au moins un dispatcheur actif",
    any(compte.role is Role.DISPATCHEUR and compte.actif for compte in comptes),
    "sinon plus personne ne pourrait planifier",
)

vehicules = {v.id for v in charger_tout("data").vehicules}
rattachements = {
    compte.vehicule for compte in comptes if compte.role is Role.CONDUCTEUR
}
verifier(
    "33 · chaque véhicule de la flotte a un conducteur",
    rattachements == vehicules,
    f"{len(rattachements)} conducteur(s) pour {len(vehicules)} véhicule(s)",
)

# =====================================================================

print()
print("=" * 72)
print("  Contrôle de l'authentification et du contrôle d'accès")
print("=" * 72)
for libelle, ok, detail in resultats:
    print(f"  [{'OK ' if ok else 'ECHEC'}] {libelle}")
    if detail:
        print(f"          {detail}")
reussis = sum(1 for _, ok, _ in resultats if ok)
print("-" * 72)
print(f"  {reussis}/{len(resultats)} critères d'acceptation vérifiés")
print("=" * 72)
print()
raise SystemExit(0 if reussis == len(resultats) else 1)
