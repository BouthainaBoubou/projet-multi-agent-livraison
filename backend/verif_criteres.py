"""Contrôle des ajouts du 20/08/2026 : classification, fragilité,
confidentialité, trafic horaire.

Même esprit que `verif_agents.py` : une liste de critères d'acceptation,
chacun vrai ou faux, aucun commentaire d'humeur. À lancer depuis
`backend/` :

    python verif_criteres.py
"""

from src.agents.coordinator_agent import CoordinatorAgent, CommandesIncompletes
from src.data.loader import charger_tout
from src.models.commande import (
    Fragilite, NiveauService, Priorite, StatutCommande, TypeClient,
)

resultats: list[tuple[str, bool, str]] = []


def verifier(libelle: str, condition: bool, detail: str = "") -> None:
    resultats.append((libelle, bool(condition), detail))


def neuf() -> CoordinatorAgent:
    """Un système propre, rechargé depuis les fichiers."""
    return CoordinatorAgent(charger_tout("data"))


# =====================================================================
# 1. Critères de classification des commandes
# =====================================================================

c = neuf()
plan = c.planifier()
reference = c.score()

verifier(
    "01 · les 28 commandes du fichier sont classées",
    len(c.commandes_a_completer()) == 0,
)
verifier(
    "02 · la priorité est calculée, pas lue",
    c.order.trouver_commande_par_id("C002").priorite is Priorite.HAUTE
    and c.order.trouver_commande_par_id("C004").priorite is Priorite.BASSE,
)
verifier(
    "03 · la grille distingue le grand compte du client courant",
    c.order.trouver_commande_par_id("C013").priorite is Priorite.HAUTE
    and c.order.trouver_commande_par_id("C001").priorite is Priorite.NORMALE,
    "C013 standard/grand compte = HAUTE, C001 standard/courant = NORMALE",
)

# --- Blocage : une commande non classée arrête toute la chaîne ---

c = neuf()
c.order.trouver_commande_par_id("C007").fragilite = None
c.order.trouver_commande_par_id("C007").rafraichir_statut()

verifier(
    "04 · une commande sans critère passe au statut INCOMPLETE",
    c.order.trouver_commande_par_id("C007").statut is StatutCommande.INCOMPLETE,
)
verifier(
    "05 · elle sort du vivier de planification",
    all(cmd.id != "C007" for cmd in c.order.commandes_en_attente()),
)
try:
    c.planifier()
    bloque, message = False, "la planification a démarré malgré tout"
except CommandesIncompletes as refus:
    bloque, message = True, str(refus)
verifier("06 · la planification est refusée", bloque, message)
verifier(
    "07 · le système dit quelle commande et quel critère",
    c.commandes_a_completer() == {"C007": ["fragilite"]},
    str(c.commandes_a_completer()),
)
verifier(
    "08 · il propose les valeurs acceptées, sans texte libre",
    c.valeurs_a_proposer("C007")
    == {"fragilite": ["standard", "fragile", "tres_fragile"]},
)

# --- Saisie à la main : le dispatcheur débloque ---

c.completer_commande("C007", fragilite="standard")
verifier(
    "09 · la saisie fait repasser la commande en attente",
    c.order.trouver_commande_par_id("C007").statut is StatutCommande.EN_ATTENTE,
)
verifier(
    "10 · la saisie est tracée avec son auteur",
    c.journal[-1].type == "saisie" and c.journal[-1].auteur == "dispatcheur",
    c.journal_texte().splitlines()[-1],
)
c.planifier()
verifier(
    "11 · une fois complétée, le plan retrouve la référence",
    c.score()["Z"] == reference["Z"],
    f"Z = {c.score()['Z']} (référence {reference['Z']})",
)

# --- Aucune valeur inventée, aucune valeur inconnue acceptée ---

try:
    c.modifier_commande("C007", fragilite="tres tres fragile")
    refuse = False
except ValueError:
    refuse = True
verifier("12 · une valeur inconnue est refusée, pas remplacée", refuse)

c = neuf()
c.planifier()
c.order.marquer_livree("C001")
try:
    c.modifier_commande("C001", niveau_service="express")
    refuse = False
except ValueError:
    refuse = True
verifier("13 · une commande livrée n'est plus reclassable", refuse)

# --- Le client change d'avis : replanification ---

c = neuf()
c.planifier()
z_avant = c.score()["Z"]
c.modifier_commande("C004", niveau_service="express")
verifier(
    "14 · un changement de critère déclenche un nouveau calcul",
    c.journal[-1].type == "modification" and c.journal[-1].variation is not None,
    f"ΔZ = {c.journal[-1].variation}",
)
verifier(
    "15 · le changement remonte bien dans la priorité",
    c.order.trouver_commande_par_id("C004").priorite is Priorite.HAUTE,
)

# =====================================================================
# 2. Fragilité des produits
# =====================================================================

c = neuf()
c.planifier()

verifier(
    "16 · un lot très fragile part sur un véhicule équipé",
    all(
        c.vehicle.trouver_vehicule_par_id(cmd.vehicule_assigne).equipement_fragile
        for cmd in c.donnees.commandes
        if cmd.fragilite is Fragilite.TRES_FRAGILE and cmd.vehicule_assigne
    ),
    ", ".join(
        f"{cmd.id}->{cmd.vehicule_assigne}"
        for cmd in c.donnees.commandes
        if cmd.fragilite is Fragilite.TRES_FRAGILE
    ),
)
verifier(
    "17 · aucun lot ne dépasse sa limite de manutentions",
    all(
        tournee.arrets.index(
            c.order.trouver_commande_par_id(id_cmd).destination
        ) - 1 <= (c.order.trouver_commande_par_id(id_cmd).manutentions_max or 99)
        for tournee in c.plan.tournees
        for id_cmd in tournee.commandes
    ),
)
verifier(
    "18 · le risque de casse est chiffré et entre dans Z",
    c.score()["risque_fragilite"] > 0,
    f"risque = {c.score()['risque_fragilite']}",
)

# --- Sans véhicule équipé, le lot est rejeté avec un motif clair ---

c = neuf()
for vehicule in c.donnees.vehicules:
    vehicule.equipement_fragile = False
c.planifier()
motifs = {rejet.commande_id: rejet.motif for rejet in c.plan.rejets}
verifier(
    "19 · sans matériel adapté, le très fragile est refusé, pas dégradé",
    all(
        cmd.id in motifs
        for cmd in c.donnees.commandes
        if cmd.fragilite is Fragilite.TRES_FRAGILE
    ),
    "; ".join(f"{k} : {v}" for k, v in motifs.items()),
)
verifier(
    "20 · le motif nomme le matériel manquant",
    any("équipé" in motif for motif in motifs.values()),
)

# --- Ce que coûte la prise en compte de la fragilité ---

c = neuf()
for cmd in c.donnees.commandes:
    cmd.fragilite = Fragilite.STANDARD
c.planifier()
sans = c.score()
verifier(
    "21 · fragilité neutralisée, on retrouve exactement l'ancien plan",
    sans["Z"] == 25774.0 and sans["distance_km"] == 9714.0,
    f"Z = {sans['Z']}, {sans['distance_km']} km (référence du 19/08 : 25774 / 9714)",
)
verifier(
    "22 · la fragilité coûte, mais ne dégrade pas le service",
    reference["commandes_servies"] == sans["commandes_servies"],
    f"{reference['commandes_servies']} commandes servies dans les deux cas, "
    f"surcoût {reference['Z'] - sans['Z']:+.0f} de Z "
    f"({reference['distance_km'] - sans['distance_km']:+.0f} km)",
)

# =====================================================================
# 3. Données confidentielles
# =====================================================================

c = neuf()
c.planifier()
sensible = next(cmd for cmd in c.donnees.commandes if cmd.est_sensible)
vue_dispatcheur = c.order.vue(sensible.id, "dispatcheur")
vue_conducteur = c.order.vue(sensible.id, "conducteur")

verifier(
    "23 · le dispatcheur voit tout d'une commande sensible",
    vue_dispatcheur["poids"] == sensible.poids
    and vue_dispatcheur["priorite"] is not None,
)
verifier(
    "24 · le conducteur ne voit ni poids, ni priorité, ni classification",
    "poids" not in vue_conducteur and "priorite" not in vue_conducteur
    and "niveau_service" not in vue_conducteur,
    str(vue_conducteur),
)
verifier(
    "25 · il conserve ce qu'il lui faut pour livrer",
    vue_conducteur["destination"] == sensible.destination
    and vue_conducteur["confidentiel"] is True,
)

ordinaire = next(cmd for cmd in c.donnees.commandes if not cmd.est_sensible)
verifier(
    "26 · une commande ordinaire reste lisible par le conducteur",
    c.order.vue(ordinaire.id, "conducteur")["poids"] == ordinaire.poids,
)

try:
    c.order.vue(ordinaire.id, "comptabilite")
    refuse = False
except ValueError:
    refuse = True
verifier("27 · un rôle inconnu n'obtient rien", refuse)

vehicule_avec_sensible = next(
    tournee.vehicule_id for tournee in c.plan.tournees
    if sensible.id in tournee.commandes
)
feuille = c.feuille_de_route(vehicule_avec_sensible, "conducteur")
verifier(
    "28 · la feuille de route du conducteur applique le masquage",
    all(
        "poids" not in vue
        for vue in feuille["commandes"] if vue.get("confidentiel")
    ),
)
verifier(
    "29 · aucune donnée client ne sort vers un service externe",
    "geometrie" not in open("src/agents/optimization_agent.py", encoding="utf-8").read()
    and "geometrie" not in open("src/agents/route_agent.py", encoding="utf-8").read(),
    "aucun agent n'importe le service de géométrie",
)

# =====================================================================
# 4. Trafic pris en compte
# =====================================================================

mesures = {}
for heure in (3, 6, 8, 12, 18, 22):
    c = neuf()
    c.definir_heure_depart(heure)
    c.planifier()
    mesures[heure] = c.score()

verifier(
    "30 · l'heure de départ change le plan",
    len({m["Z"] for m in mesures.values()}) > 1,
    " · ".join(f"{h:02d}h : Z = {m['Z']:.0f}" for h, m in mesures.items()),
)
# À itinéraire fixé, l'effet du trafic est monotone et se mesure
# directement. Sur Z, il ne l'est pas : le glouton change d'affectation
# quand les temps bougent, et une heure un peu plus chargée peut
# produire un meilleur regroupement. C'est une propriété de
# l'heuristique, pas une erreur — et c'est une des raisons de comparer
# un jour le glouton à un solveur.
temps = {}
for heure in (3, 8, 12, 18):
    c = neuf()
    c.definir_heure_depart(heure)
    temps[heure] = c.route.temps_trajet("CASA", "TNG")

verifier(
    "31 · à itinéraire fixé, la pointe coûte plus de temps que la nuit",
    temps[18] > temps[12] > temps[3] and temps[8] > temps[3],
    " · ".join(f"{h:02d}h : {t:.0f} min" for h, t in temps.items())
    + "  (Casablanca – Tanger)",
)
verifier(
    "32 · la pointe du matin coûte plus cher que le creux de journée",
    mesures[8]["Z"] > mesures[12]["Z"],
    f"08h : {mesures[8]['Z']:.0f} · 12h : {mesures[12]['Z']:.0f}",
)

c = neuf()
c.definir_heure_depart(8)
ferry = c.traffic.trouver_troncon("TMED", "ALG")
verifier(
    "33 · la traversée maritime ne se congestionne pas",
    ferry.niveau_trafic == 1.0,
)
verifier(
    "34 · un accès portuaire souffre plus qu'une autoroute",
    c.traffic.trouver_troncon("TNG", "TMED").niveau_trafic
    > c.traffic.trouver_troncon("ALG", "MAD").niveau_trafic,
    f"TNG–TMED : {c.traffic.trouver_troncon('TNG', 'TMED').niveau_trafic} · "
    f"ALG–MAD : {c.traffic.trouver_troncon('ALG', 'MAD').niveau_trafic}",
)
try:
    c.definir_heure_depart(25)
    refuse = False
except ValueError:
    refuse = True
verifier("35 · une heure hors bornes est refusée", refuse)

# --- Les incidents continuent de fonctionner ---

c = neuf()
c.planifier()
z0 = c.score()["Z"]
c.declarer_panne("V004")
z_panne = c.score()["Z"]
c.declarer_reparation("V004")
verifier(
    "36 · les scénarios d'incident restent opérants",
    z_panne > z0 and c.score()["Z"] == z0,
    f"nominal {z0:.0f} -> panne {z_panne:.0f} -> réparation {c.score()['Z']:.0f}",
)
c.declarer_blocage("TMED", "ALG")
z_ferry = c.score()["Z"]
c.declarer_deblocage("TMED", "ALG")
verifier(
    "37 · le blocage du ferry reste mesurable et réversible",
    z_ferry > z0 and c.score()["Z"] == z0,
    f"blocage +{z_ferry - z0:.0f}",
)

# =====================================================================

print()
print("=" * 72)
print("  Contrôle des critères de classification, fragilité,")
print("  confidentialité et trafic — 20/08/2026")
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
print(f"  Plan de référence : Z = {reference['Z']}, "
      f"{reference['distance_km']} km, {reference['vehicules']} véhicules, "
      f"{reference['commandes_servies']} commandes servies, "
      f"risque {reference['risque_fragilite']}")
print()
raise SystemExit(0 if reussis == len(resultats) else 1)
