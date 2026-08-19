"""Vérifie que tous les fichiers du projet sont présents et à jour.

Ne teste pas le comportement — `verif_chargement.py` et `verif_agents.py`
s'en chargent. Ce script répond à une autre question : « ai-je bien
copié la dernière version de chaque fichier ? ».

Chaque fichier est identifié par des marqueurs — des bouts de texte qui
n'existent que dans la bonne version. Un fichier présent mais périmé est
signalé comme tel, ce qu'une simple vérification d'existence ne verrait
pas.

    python verif_fichiers.py
"""

import json
from pathlib import Path

# fichier -> marqueurs qui doivent tous s'y trouver
ATTENDUS: dict[str, list[str]] = {
    # --- modèles ---
    "src/models/noeud.py": ["class TypeNoeud", "duree_traitement_min",
                            "est_point_de_passage"],
    "src/models/route.py": ["class ModeTransport", "attente_frontiere_min",
                            "franchit_frontiere"],
    "src/models/commande.py": ["class TypeLivraison", "origine: str",
                               "est_internationale"],
    "src/models/vehicule.py": ["CONDUITE_JOURNALIERE_MAX_MIN",
                               "conduite_restante_min", "autorise_international"],
    "src/models/tournee.py": ["class Tournee", "class Rejet", "class Plan"],

    # --- chargement ---
    "src/data/loader.py": ["_verifier_coherence_internationale",
                           "_renseigner_type_livraison", "_vers_booleen"],

    # --- agents ---
    "src/agents/order_agent.py": ["commandes_par_type", "remettre_en_attente",
                                  "poids_total_en_attente"],
    "src/agents/vehicle_agent.py": ["remettre_en_service",
                                    "consommer_temps_conduite",
                                    "peut_tenir_la_route"],
    "src/agents/traffic_agent.py": ["mettre_a_jour_attente_frontiere",
                                    "memes_extremites"],
    "src/agents/route_agent.py": ["class CheminIntrouvable", "itineraire_complet",
                                  "def temps_conduite", "def rafraichir"],
    "src/agents/optimization_agent.py": ["JOURS_MAX_MISSION", "def evaluer",
                                         "inaccessible", "REPOS_JOURNALIER_MIN"],
    "src/agents/coordinator_agent.py": ["declarer_reparation", "declarer_blocage",
                                        "declarer_attente_frontiere", "_liberer"],

    # --- service d'affichage ---
    "src/services/geometrie.py": ["class ServiceGeometrie", "driving-hgv",
                                  "if not trace.approximatif:"],

    # --- outils ---
    "outils/generer_carte.py": ["def vues_par_defaut", "def nom_court"],
    "outils/generer_carte_chauffeur.py": ["def nom_court", "carteDisponible"],
    "outils/preparer_cache.py": ["ServiceGeometrie", "--etat"],

    # --- scripts de vérification ---
    "verif_chargement.py": ["Gardes attendues"],
    "verif_agents.py": ["criteres satisfaits"],
    "demo_scenarios.py": ["SCÉNARIO 4"],
}

INITS = [
    "src/__init__.py", "src/models/__init__.py", "src/data/__init__.py",
    "src/agents/__init__.py", "src/services/__init__.py", "outils/__init__.py",
]

CSV_ATTENDUS = {
    "data/noeuds.csv": "id,nom,latitude,longitude,pays,type_noeud,duree_traitement_min",
    "data/routes.csv": "origine,destination,distance_km,temps_base_min,mode,"
                       "franchit_frontiere,cout_fixe_dh,niveau_trafic,"
                       "attente_frontiere_min,bloquee",
    "data/vehicules.csv": "id,capacite_kg,position_actuelle,charge_actuelle_kg,"
                          "statut,type_vehicule,pays_base,autorise_international",
    "data/commandes.csv": "id,origine,destination,poids,priorite,delai_minutes",
}

problemes: list[str] = []


def controler(libelle: str, ok: bool, detail: str = "") -> None:
    etat = "OK" if ok else "PROBLEME"
    print(f"  {etat:<9} {libelle}" + (f"   {detail}" if detail else ""))
    if not ok:
        problemes.append(libelle)


print("\n--- Fichiers de code ---")
for chemin, marqueurs in ATTENDUS.items():
    fichier = Path(chemin)
    if not fichier.is_file():
        controler(chemin, False, "fichier absent")
        continue
    contenu = fichier.read_text(encoding="utf-8", errors="replace")
    manquants = [m for m in marqueurs if m not in contenu]
    controler(
        chemin, not manquants,
        "" if not manquants else f"version périmée, il manque : {manquants}",
    )

print("\n--- Fichiers __init__.py ---")
for chemin in INITS:
    controler(chemin, Path(chemin).is_file(),
              "" if Path(chemin).is_file() else "à créer (fichier vide)")

print("\n--- Données ---")
for chemin, entete in CSV_ATTENDUS.items():
    fichier = Path(chemin)
    if not fichier.is_file():
        controler(chemin, False, "fichier absent")
        continue
    premiere = fichier.read_text(encoding="utf-8").splitlines()[0].strip()
    attendues = set(entete.split(","))
    trouvees = set(premiere.split(","))
    manquantes = attendues - trouvees
    controler(chemin, not manquantes,
              "" if not manquantes else f"colonnes manquantes : {sorted(manquantes)}")

cache = Path("data/geometries.json")
if cache.is_file():
    entrees = json.loads(cache.read_text(encoding="utf-8"))
    reels = sum(1 for e in entrees.values() if e["source"] != "droit")
    controler("data/geometries.json", reels == len(entrees) and len(entrees) > 0,
              f"{len(entrees)} tronçons, {reels} en géométrie réelle")
else:
    controler("data/geometries.json", False,
              "absent — lancer : python -m outils.preparer_cache --cle-api VOTRE_CLE")

print("\n" + "-" * 70)
if problemes:
    print(f"{len(problemes)} problème(s) à corriger :")
    for probleme in problemes:
        print(f"  - {probleme}")
else:
    print("Tout est en place et à jour.")