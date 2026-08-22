
from fastapi.testclient import TestClient

from src.api.application import construire_application
from src.models.commande import Fragilite

DISPATCH = {"identifiant": "dispatch", "mot_de_passe": "Tournees#2026!MA"}
CHAUFFEUR_1 = {"identifiant": "chauffeur.v001", "mot_de_passe": "Conduite#2026-V001"}
CHAUFFEUR_3 = {"identifiant": "chauffeur.v003", "mot_de_passe": "Conduite#2026-V003"}

Z_REFERENCE = 28625.0

resultats: list[tuple[str, bool, str]] = []


def verifier(libelle: str, condition: bool, detail: str = "") -> None:
    resultats.append((libelle, bool(condition), detail))


class Horloge:
    """Horloge pilotée à la main, pour tester l'expiration sans attendre."""

    def __init__(self) -> None:
        self.instant = 1_000_000.0

    def __call__(self) -> float:
        return self.instant

    def avancer(self, minutes: float) -> None:
        self.instant += minutes * 60


def client(horloge=None) -> TestClient:
    return TestClient(construire_application(horloge=horloge or (lambda: 1e6)))


def entete(reponse) -> dict:
    return {"Authorization": f"Bearer {reponse.json()['jeton']}"}


def connecter(c: TestClient, identifiants: dict) -> dict:
    return entete(c.post("/connexion", json=identifiants))


# =====================================================================
# 1. Accès
# =====================================================================

c = client()
r = c.post("/connexion", json=DISPATCH)
verifier(
    "01 · connexion valable, jeton délivré",
    r.status_code == 200 and len(r.json()["jeton"]) >= 32,
    f"rôle : {r.json()['role']}",
)
verifier(
    "02 · la réponse ne contient aucun mot de passe",
    "mot_de_passe" not in r.text and DISPATCH["mot_de_passe"] not in r.text,
)

mauvais = c.post("/connexion", json={**DISPATCH, "mot_de_passe": "FauxMotDePasse#1"})
inconnu = c.post("/connexion", json={"identifiant": "personne", "mot_de_passe": "FauxMotDePasse#1"})
verifier("03 · mauvais mot de passe : 401", mauvais.status_code == 401)
verifier(
    "04 · identifiant inconnu : même code, même message",
    inconnu.status_code == 401 and inconnu.json() == mauvais.json(),
    inconnu.json()["detail"],
)

verifier("05 · sans jeton : 401", c.get("/plan").status_code == 401)
verifier(
    "06 · jeton inventé : 401",
    c.get("/plan", headers={"Authorization": "Bearer nimportequoi"}).status_code == 401,
)

h = entete(r)
c.post("/deconnexion", headers=h)
verifier(
    "07 · après déconnexion, le jeton ne vaut plus rien",
    c.get("/plan", headers=h).status_code == 401,
)
verifier(
    "08 · se déconnecter deux fois reste sans effet",
    c.post("/deconnexion", headers=h).status_code == 204,
)

horloge = Horloge()
c = client(horloge)
h = connecter(c, DISPATCH)
c.post("/planifier", headers=h)
horloge.avancer(31)
verifier(
    "09 · session expirée après 30 min d'inactivité : 401",
    c.get("/plan", headers=h).status_code == 401,
)

# =====================================================================
# 2. Le plan, identique à la ligne de commande
# =====================================================================

c = client()
h = connecter(c, DISPATCH)
verifier(
    "10 · avant toute planification : 409, pas une erreur serveur",
    c.get("/plan", headers=h).status_code == 409,
)

plan = c.post("/planifier", headers=h)
verifier(
    "11 · l'API donne exactement le plan de la ligne de commande",
    plan.json()["score"]["Z"] == Z_REFERENCE,
    f"Z = {plan.json()['score']['Z']} (référence {Z_REFERENCE})",
)
verifier(
    "12 · chaque tournée porte son itinéraire déplié",
    all(len(t["itineraire"]) >= len(t["arrets"]) for t in plan.json()["tournees"]),
    "V001 : " + " → ".join(plan.json()["tournees"][0]["itineraire"]),
)
verifier(
    "13 · les rejets sont motivés",
    all(rejet["motif"] for rejet in plan.json()["rejets"]),
    "; ".join(f"{r['commande']} : {r['motif']}" for r in plan.json()["rejets"]),
)

douze = c.post("/heure-depart", json={"heure": 12}, headers=h).json()["score"]["Z"]
dix_huit = c.post("/heure-depart", json={"heure": 18}, headers=h).json()["score"]["Z"]
verifier(
    "14 · l'heure de départ change le plan",
    douze != dix_huit,
    f"12 h : Z = {douze} · 18 h : Z = {dix_huit}",
)
verifier(
    "15 · une heure hors bornes est refusée avant d'atteindre le domaine",
    c.post("/heure-depart", json={"heure": 25}, headers=h).status_code == 422,
)

# =====================================================================
# 3. Le blocage des commandes non classées
# =====================================================================

c = client()
h = connecter(c, DISPATCH)
commande = c.app.state.etat.coordinateur.order.trouver_commande_par_id("C007")
commande.fragilite = None
commande.rafraichir_statut()

refus = c.post("/planifier", headers=h)
verifier(
    "16 · planifier est refusé, en 409 et non en 500",
    refus.status_code == 409,
)
verifier(
    "17 · la réponse dit quelle commande et quel critère",
    refus.json()["detail"]["commandes_a_completer"] == {"C007": ["fragilite"]},
    str(refus.json()["detail"]["commandes_a_completer"]),
)
verifier(
    "18 · elle fournit les valeurs acceptées, pour l'écran de saisie",
    refus.json()["detail"]["valeurs_possibles"]["fragilite"]
    == ["standard", "fragile", "tres_fragile"],
)

liste = c.get("/commandes/a-completer", headers=h)
verifier(
    "19 · l'adresse dédiée renvoie la même liste de travail",
    liste.json()["commandes"] == {"C007": ["fragilite"]},
)

saisie = c.post(
    "/commandes/C007/criteres", json={"fragilite": "standard"}, headers=h
)
verifier(
    "20 · la saisie débloque la commande",
    saisie.status_code == 200 and saisie.json()["geste"] == "saisie"
    and saisie.json()["commandes_a_completer"] == {},
)
verifier(
    "21 · une fois complétée, le plan retrouve la référence",
    c.post("/planifier", headers=h).json()["score"]["Z"] == Z_REFERENCE,
)

verifier(
    "22 · une valeur inconnue est refusée par le contrat (422)",
    c.post(
        "/commandes/C007/criteres",
        json={"fragilite": "tres tres fragile"}, headers=h,
    ).status_code == 422,
)
verifier(
    "23 · une commande inconnue : 404",
    c.post(
        "/commandes/C999/criteres", json={"fragilite": "standard"}, headers=h
    ).status_code == 404,
)

modif = c.post(
    "/commandes/C004/criteres", json={"niveau_service": "express"}, headers=h
)
verifier(
    "24 · le client change d'avis : c'est une modification, pas une saisie",
    modif.status_code == 200 and modif.json()["geste"] == "modification",
    f"C004 devient {modif.json()['commande']['priorite']}",
)

# =====================================================================
# 4. Les incidents
# =====================================================================

c = client()
h = connecter(c, DISPATCH)
nominal = c.post("/planifier", headers=h).json()["score"]["Z"]
panne = c.post("/incident", json={"type": "panne", "vehicule": "V001"}, headers=h)
repare = c.post(
    "/incident", json={"type": "reparation", "vehicule": "V001"}, headers=h
)
verifier(
    "25 · panne puis réparation : Z monte, puis revient exactement",
    panne.json()["score"]["Z"] > nominal
    and repare.json()["score"]["Z"] == nominal,
    f"{nominal} → {panne.json()['score']['Z']} → {repare.json()['score']['Z']}",
)

ferry = c.post(
    "/incident",
    json={"type": "blocage", "origine": "TMED", "destination": "ALG"},
    headers=h,
)
verifier(
    "26 · blocage du ferry : l'export tombe",
    len(ferry.json()["rejets"]) >= 8,
    f"ΔZ = {ferry.json()['score']['Z'] - nominal:+.0f}, "
    f"{len(ferry.json()['rejets'])} rejets",
)
c.post(
    "/incident",
    json={"type": "deblocage", "origine": "TMED", "destination": "ALG"},
    headers=h,
)

verifier(
    "27 · un champ manquant donne un 400 explicite",
    c.post("/incident", json={"type": "panne"}, headers=h).status_code == 400,
)
verifier(
    "28 · un type d'incident inconnu est refusé par le contrat",
    c.post("/incident", json={"type": "meteo"}, headers=h).status_code == 422,
)
verifier(
    "29 · un véhicule inconnu donne un 400, pas un 500",
    c.post(
        "/incident", json={"type": "panne", "vehicule": "V999"}, headers=h
    ).status_code == 400,
)

# =====================================================================
# 5. Le moindre privilège, à travers l'API
# =====================================================================

c = client()
h_dispatch = connecter(c, DISPATCH)
c.post("/planifier", headers=h_dispatch)
h_v001 = connecter(c, CHAUFFEUR_1)

for adresse, methode in (
    ("/planifier", c.post), ("/plan", c.get), ("/journal", c.get),
    ("/commandes/a-completer", c.get),
):
    verifier(
        f"30 · le conducteur ne peut pas atteindre {adresse}",
        methode(adresse, headers=h_v001).status_code == 403,
    )
verifier(
    "31 · il ne peut pas déclarer d'incident",
    c.post(
        "/incident", json={"type": "panne", "vehicule": "V001"}, headers=h_v001
    ).status_code == 403,
)

verifier(
    "32 · il consulte sa propre mission",
    c.get("/tournee/V001", headers=h_v001).status_code == 200,
)
verifier(
    "33 · il ne consulte pas celle d'un collègue",
    c.get("/tournee/V003", headers=h_v001).status_code == 403,
    c.get("/tournee/V003", headers=h_v001).json()["detail"],
)
verifier(
    "34 · ajouter ?role=dispatcheur n'y change rien",
    c.get("/tournee/V003?role=dispatcheur", headers=h_v001).status_code == 403,
    "le rôle vient du compte, le paramètre n'existe pas",
)
verifier(
    "35 · le dispatcheur, lui, voit toutes les missions",
    c.get("/tournee/V003", headers=h_dispatch).status_code == 200,
)

h_v003 = connecter(c, CHAUFFEUR_3)
verifier(
    "36 · chaque conducteur est cantonné à son véhicule",
    c.get("/tournee/V003", headers=h_v003).status_code == 200
    and c.get("/tournee/V001", headers=h_v003).status_code == 403,
)

# =====================================================================
# 6. Le masquage traverse l'API intact
# =====================================================================

vue_conducteur = c.get("/tournee/V001", headers=h_v001).json()
sensibles = [cmd for cmd in vue_conducteur["commandes"] if cmd.get("confidentiel")]
verifier(
    "37 · les commandes sensibles arrivent masquées chez le conducteur",
    sensibles and all("poids" not in cmd for cmd in sensibles),
    f"{len(sensibles)} masquée(s) : "
    + ", ".join(cmd["id"] for cmd in sensibles),
)
verifier(
    "38 · le poids d'une commande sensible n'apparaît nulle part dans la réponse",
    all(
        str(int(cmd["poids"])) not in c.get("/tournee/V001", headers=h_v001).text
        for cmd in c.get("/tournee/V001", headers=h_dispatch).json()["commandes"]
        if cmd.get("confidentiel")
    ),
)
verifier(
    "39 · le dispatcheur voit le détail complet",
    all("poids" in cmd for cmd in
        c.get("/tournee/V001", headers=h_dispatch).json()["commandes"]),
)

# =====================================================================
# 7. Traçabilité
# =====================================================================

c = client()
h = connecter(c, DISPATCH)
commande = c.app.state.etat.coordinateur.order.trouver_commande_par_id("C010")
commande.fragilite = None
commande.rafraichir_statut()
c.post("/commandes/C010/criteres", json={"fragilite": "fragile"}, headers=h)
c.post("/planifier", headers=h)

journal = c.get("/journal", headers=h).json()
verifier(
    "40 · le journal retient qui a saisi",
    any(e["auteur"] == "dispatch" and e["type"] == "saisie" for e in journal),
    next(e["description"] for e in journal if e["type"] == "saisie"),
)
verifier(
    "41 · chaque replanification porte son écart de Z",
    any(e["variation"] is not None for e in journal)
    or len([e for e in journal if e["type"] == "planification"]) == 1,
)

connexions = c.get("/journal/connexions", headers=h)
verifier(
    "42 · le journal des connexions est consultable par le dispatcheur",
    connexions.status_code == 200 and len(connexions.json()) >= 1,
)
verifier(
    "43 · aucun mot de passe n'y figure",
    DISPATCH["mot_de_passe"] not in connexions.text,
)

# =====================================================================
# 8. La documentation du contrat
# =====================================================================

verifier(
    "44 · le contrat est publié pour le frontend",
    c.get("/openapi.json").status_code == 200,
    f"{len(c.get('/openapi.json').json()['paths'])} adresses documentées, "
    f"visibles sur /docs",
)
# Contrôle sur le contrat lui-même, et non sur une réponse : aucune
# adresse ne doit seulement *accepter* un paramètre `role`. Le critère 34
# montre qu'en écrire un ne sert à rien ; celui-ci montre qu'il n'existe
# pas.
parametres = {
    parametre.get("name")
    for chemin in c.get("/openapi.json").json()["paths"].values()
    for operation in chemin.values()
    for parametre in operation.get("parameters", [])
}
verifier(
    "45 · aucune adresse n'accepte de paramètre « role »",
    "role" not in parametres,
    f"paramètres acceptés : {sorted(p for p in parametres if p)}",
)

# =====================================================================

print()
print("=" * 72)
print("  Contrôle de l'API HTTP")
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
