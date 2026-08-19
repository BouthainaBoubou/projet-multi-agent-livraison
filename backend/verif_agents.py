"""Vérifie les critères d'acceptation des deux agents ajoutés.

Un test par ligne du tableau des critères. Le script ne dépend d'aucun
cadre de test : il s'exécute avec `python verif_agents.py` et affiche
OK ou ECHEC pour chaque point.
"""

from time import perf_counter

import networkx as nx

from src.agents.coordinator_agent import CoordinatorAgent
from src.agents.optimization_agent import (
    CONDUITE_JOURNALIERE_MAX_MIN, OptimizationAgent,
)
from src.agents.route_agent import RouteAgent
from src.data.loader import charger_tout
from src.models.commande import StatutCommande

resultats: list[tuple[str, bool, str]] = []


def verifier(libelle: str, condition: bool, detail: str = "") -> None:
    resultats.append((libelle, condition, detail))


donnees = charger_tout("data")
route = RouteAgent(donnees.noeuds, donnees.troncons)

# ============================ RouteAgent =============================

verifier(
    "T1 graphe connexe, 21 noeuds, 28 aretes",
    nx.is_connected(route.graphe)
    and route.graphe.number_of_nodes() == 21
    and route.graphe.number_of_edges() == 28,
    f"{route.graphe.number_of_nodes()} noeuds, {route.graphe.number_of_edges()} aretes",
)

chemin = route.plus_court_chemin("CASA", "AGA")
verifier("T2 CASA -> AGA passe par Marrakech",
         chemin == ["CASA", "MRK", "AGA"], " -> ".join(chemin))

aller = route.plus_court_chemin("CASA", "PAR")
retour = route.plus_court_chemin("PAR", "CASA")
verifier("T3 chemin symetrique (graphe non oriente)",
         retour == list(reversed(aller)), f"{len(aller)} noeuds")

arcs = route._sommer(chemin, "temps")
traitement = sum(route.noeuds[n].duree_traitement_min for n in chemin[1:])
verifier(
    "T5 temps_trajet = aretes + traitement des noeuds atteints",
    abs(route.temps_trajet("CASA", "AGA") - (arcs + traitement)) < 1e-9,
    f"{arcs:.0f} + {traitement:.0f} = {route.temps_trajet('CASA', 'AGA'):.0f} min",
)

depart = perf_counter()
matrice = route.matrice_temps([n.id for n in donnees.noeuds])
duree_matrice = perf_counter() - depart
verifier("T6 matrice 21x21 en moins d'une seconde",
         len(matrice) == 441 and duree_matrice < 1.0,
         f"{len(matrice)} paires en {duree_matrice * 1000:.0f} ms")

itineraire = route.itineraire_complet(["CASA", "MAD"])
verifier(
    "T7 itineraire_complet deplie les noeuds traverses",
    itineraire == ["CASA", "RAB", "TNG", "TMED", "ALG", "MAD"],
    " -> ".join(itineraire),
)

# Test T4 en dernier : il modifie le reseau.
coordinateur = CoordinatorAgent(charger_tout("data"))
coordinateur.traffic.bloquer_troncon("TMED", "ALG")
coordinateur.route.rafraichir()
verifier("T4 ferry coupe -> Madrid inaccessible",
         not coordinateur.route.chemin_existe("CASA", "MAD"))
coordinateur.traffic.debloquer_troncon("TMED", "ALG")
coordinateur.route.rafraichir()

# ========================= OptimizationAgent =========================

coordinateur.planifier()
plan = coordinateur.plan
par_id = {c.id: c for c in donnees.commandes}
vehicules = {v.id: v for v in coordinateur.donnees.vehicules}

servies = {c for t in plan.tournees for c in t.commandes}
rejetees = {r.commande_id for r in plan.rejets}
verifier(
    "O1 toute commande est servie ou rejetee avec motif",
    servies | rejetees == {c.id for c in donnees.commandes}
    and all(r.motif for r in plan.rejets),
    f"{len(servies)} servies, {len(rejetees)} rejetees",
)

verifier(
    "O2 aucune capacite depassee",
    all(t.charge_kg <= vehicules[t.vehicule_id].capacite_kg for t in plan.tournees),
)

verifier(
    "O3 conduite compatible avec le nombre de journees",
    all(t.conduite_min <= t.jours * CONDUITE_JOURNALIERE_MAX_MIN
        for t in plan.tournees),
    "max " + str(max(t.conduite_min for t in plan.tournees)) + " min",
)

commandes_par_id = {c.id: c for c in coordinateur.donnees.commandes}
verifier(
    "O4 aucune commande internationale sur un vehicule non autorise",
    all(
        vehicules[t.vehicule_id].autorise_international
        for t in plan.tournees
        for c in t.commandes
        if commandes_par_id[c].est_internationale
    ),
)

note_1 = coordinateur.optimisation.evaluer(plan)
note_2 = coordinateur.optimisation.evaluer(plan)
verifier("O5 evaluer() est reproductible",
         note_1 == note_2, f"Z = {note_1['Z']}")

# --- O6 : la panne, coeur de la demonstration ---
z_avant = coordinateur.score()["Z"]
cible = plan.tournees[0]
commandes_perdues = list(cible.commandes)

coordinateur.declarer_panne(cible.vehicule_id)
z_apres = coordinateur.score()["Z"]

statuts = {commandes_par_id[c].statut for c in commandes_perdues}
reaffectees = {
    c for t in coordinateur.plan.tournees for c in t.commandes
} & set(commandes_perdues)
verifier(
    "O6 panne : commandes liberees puis reaffectees, Z recalcule",
    StatutCommande.EN_ATTENTE not in statuts
    and len(reaffectees) > 0
    and z_apres != z_avant,
    f"{len(reaffectees)}/{len(commandes_perdues)} reaffectees, "
    f"Z {z_avant} -> {z_apres}",
)

coordinateur.declarer_reparation(cible.vehicule_id)
verifier(
    "O7 retour au nominal : Z retrouve sa valeur d'origine",
    coordinateur.score()["Z"] == z_avant,
    f"{coordinateur.score()['Z']} vs {z_avant}",
)

# ============================== Rapport ==============================

print(f"{'CRITERE':<58} {'ETAT':<7} DETAIL")
print("-" * 100)
for libelle, ok, detail in resultats:
    print(f"{libelle:<58} {'OK' if ok else 'ECHEC':<7} {detail}")

echecs = sum(1 for _, ok, _ in resultats if not ok)
print("-" * 100)
print(f"{len(resultats) - echecs}/{len(resultats)} criteres satisfaits")