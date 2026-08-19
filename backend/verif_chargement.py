"""Vérification de bout en bout du chargement et des trois agents.

Script jetable de contrôle : il ne fait pas partie de l'application, il
sert à prouver que les données et les modèles sont cohérents après le
changement de périmètre.
"""

from src.agents.order_agent import OrderAgent
from src.agents.traffic_agent import TrafficAgent
from src.agents.vehicle_agent import VehicleAgent
from src.data.loader import charger_tout
from src.models.commande import TypeLivraison

donnees = charger_tout("data")

print("--- Chargement ---")
print(f"noeuds      : {len(donnees.noeuds)}")
print(f"troncons    : {len(donnees.troncons)}")
print(f"vehicules   : {len(donnees.vehicules)}")
print(f"commandes   : {len(donnees.commandes)}")

pays = sorted({noeud.pays for noeud in donnees.noeuds})
print(f"pays        : {pays}")

order = OrderAgent(donnees.commandes)
vehicle = VehicleAgent(donnees.vehicules)
traffic = TrafficAgent(donnees.troncons)

nationales = order.commandes_par_type(TypeLivraison.NATIONALE)
internationales = order.commandes_par_type(TypeLivraison.INTERNATIONALE)
print("\n--- OrderAgent ---")
print(f"nationales      : {len(nationales)} / {order.poids_total_en_attente(TypeLivraison.NATIONALE):.0f} kg")
print(f"internationales : {len(internationales)} / {order.poids_total_en_attente(TypeLivraison.INTERNATIONALE):.0f} kg")
print("3 plus urgentes (international) :", [
    (c.id, c.priorite.name, c.delai_minutes)
    for c in order.commandes_par_urgence(TypeLivraison.INTERNATIONALE)[:3]
])

print("\n--- VehicleAgent ---")
print(f"disponibles national      : {[v.id for v in vehicle.vehicules_disponibles()]}")
print(f"disponibles international : {[v.id for v in vehicle.vehicules_disponibles(pour_international=True)]}")
print(f"capacite dispo nationale  : {vehicle.capacite_disponible_totale():.0f} kg")

vehicle.consommer_temps_conduite("V004", 540)
print(f"apres 9 h de conduite, V004 disponible ? {vehicle.trouver_vehicule_par_id('V004').disponible}")
vehicle.reinitialiser_journee("V004")
print(f"apres repos journalier, V004 disponible ? {vehicle.trouver_vehicule_par_id('V004').disponible}")

print("\n--- TrafficAgent ---")
ferry = traffic.trouver_troncon("ALG", "TMED")   # recherche symetrique
print(f"ferry trouve en sens inverse : {ferry is not None}")
print(f"temps reel avant attente : {ferry.temps_reel_min:.0f} min")
traffic.mettre_a_jour_attente_frontiere("TMED", "ALG", 300)
print(f"temps reel avec 5 h d'attente : {ferry.temps_reel_min:.0f} min")
print(f"troncons transfrontaliers : {[(t.origine, t.destination) for t in traffic.troncons_transfrontaliers()]}")

traffic.bloquer_troncon("CASA", "MRK")
print(f"praticables apres blocage : {len(traffic.troncons_praticables())} / {len(donnees.troncons)}")

print("\n--- Gardes attendues (doivent lever une erreur) ---")
for libelle, action in (
    ("trafic sur un troncon maritime",
     lambda: traffic.mettre_a_jour_trafic("TMED", "ALG", 1.5)),
    ("attente frontiere sur un troncon national",
     lambda: traffic.mettre_a_jour_attente_frontiere("CASA", "RAB", 30)),
    ("conduite au-dela du quota journalier",
     lambda: vehicle.consommer_temps_conduite("V005", 700)),
    ("chargement au-dela de la capacite",
     lambda: vehicle.charger("V007", 5000)),
):
    try:
        action()
    except ValueError as erreur:
        print(f"OK  {libelle} -> {erreur}")
    else:
        print(f"ECHEC {libelle} : aucune erreur levee")

print("\nVerification terminee.")