"""Point d'entrée de vérification : charge un scénario et affiche un résumé.

Ce fichier ne contient aucune logique métier. Il sert uniquement à
vérifier manuellement que le chargement et les agents fonctionnent.
"""

from pathlib import Path

from src.agents.order_agent import OrderAgent
from src.data.loader import DonneesLivraison, charger_tout
from src.agents.vehicle_agent import VehicleAgent
from src.agents.traffic_agent import TrafficAgent

DOSSIER_DONNEES = Path(__file__).parent / "data"


def afficher_resume(donnees: DonneesLivraison) -> None:
    """Affiche les chiffres clés du scénario chargé."""
    poids_total = sum(commande.poids for commande in donnees.commandes)
    capacite_totale = sum(v.capacite_kg for v in donnees.vehicules)
    urgentes = sum(1 for c in donnees.commandes if c.est_urgente)
    disponibles = sum(1 for v in donnees.vehicules if v.disponible)

    print("=" * 52)
    print(f"  Scénario chargé depuis : {DOSSIER_DONNEES}")
    print("=" * 52)
    print(f"  Noeuds          : {len(donnees.noeuds)}")
    print(f"  Tronçons        : {len(donnees.troncons)}")
    print(f"  Commandes       : {len(donnees.commandes)}"
          f"  (dont {urgentes} urgentes)")
    print(f"  Véhicules       : {len(donnees.vehicules)}"
          f"  (dont {disponibles} disponibles)")
    print("-" * 52)
    print(f"  Poids total     : {poids_total:.0f} kg")
    print(f"  Capacité totale : {capacite_totale:.0f} kg")

    if poids_total > capacite_totale:
        print("  /!\\ Charge supérieure à la capacité : "
              "plusieurs tournées seront nécessaires.")
    else:
        marge = 100 * (1 - poids_total / capacite_totale)
        print(f"  Marge disponible : {marge:.0f} %")
    print("=" * 52)

def tester_order_agent(donnees: DonneesLivraison) -> None:
    """Vérifie manuellement le comportement de l'agent des commandes."""
    agent = OrderAgent(donnees.commandes)

    print("\n  --- OrderAgent ---")
    print(f"  En attente : {len(agent.commandes_en_attente())}")

    print("  Cinq plus urgentes :")
    for commande in agent.commandes_par_urgence()[:5]:
        print(f"    {commande.id} - {commande.priorite.name:8} - "
              f"{commande.delai_minutes} min")

    agent.assigner_commande("C001", "V001")
    print(f"  Après assignation de C001 : "
          f"{len(agent.commandes_en_attente())} en attente")

    introuvable = agent.trouver_commande_par_id("C999")
    print(f"  Recherche de C999 : {introuvable}")

    try:
        agent.assigner_commande("C001", "V002")
    except ValueError as erreur:
        print(f"  Réassignation refusée : {erreur}")

def tester_vehicle_agent(donnees: DonneesLivraison) -> None:
    """Vérifie manuellement le comportement de l'agent des véhicules."""
    agent = VehicleAgent(donnees.vehicules)

    print("\n  --- VehicleAgent ---")
    print(f"  Disponibles : {len(agent.vehicules_disponibles())}")
    print(f"  V001 peut charger 500 kg : {agent.peut_charger('V001', 500)}")

    agent.charger("V001", 500)
    v001 = agent.trouver_vehicule_par_id("V001")
    print(f"  Après chargement : {v001.charge_actuelle_kg} kg, "
          f"reste {v001.capacite_restante} kg")

    try:
        agent.charger("V004", 900)
    except ValueError as erreur:
        print(f"  Surcharge refusée : {erreur}")

    agent.signaler_panne("V003")
    print(f"  Après panne de V003 : "
          f"{len(agent.vehicules_disponibles())} disponibles")

def tester_traffic_agent(donnees: DonneesLivraison) -> None:
    """Vérifie manuellement le comportement de l'agent de trafic."""
    agent = TrafficAgent(donnees.troncons)

    print("\n  --- TrafficAgent ---")
    print(f"  Praticables : {len(agent.troncons_praticables())} / "
          f"{len(donnees.troncons)}")

    agent.bloquer_troncon("D", "Z6")
    print(f"  Après blocage de D -> Z6 : "
          f"{len(agent.troncons_praticables())} praticables")

    agent.mettre_a_jour_trafic("D", "Z1", 2.1)
    troncon = agent.trouver_troncon("D", "Z1")
    print(f"  D -> Z1 : base {troncon.temps_base_min} min, "
          f"trafic {troncon.niveau_trafic}, "
          f"réel {troncon.temps_reel_min:.0f} min")

    try:
        agent.bloquer_troncon("D", "Z99")
    except ValueError as erreur:
        print(f"  Blocage refusé : {erreur}")

    agent.debloquer_troncon("D", "Z6")
    print(f"  Après déblocage : {len(agent.troncons_praticables())} praticables")


def main() -> None:
    """Charge les données et affiche le résumé, ou l'erreur rencontrée."""
    try:
        donnees = charger_tout(DOSSIER_DONNEES)
    except (FileNotFoundError, ValueError) as erreur:
        print(f"\n[ERREUR DE CHARGEMENT] {erreur}\n")
        return

    afficher_resume(donnees)
    tester_order_agent(donnees)
    tester_vehicle_agent(donnees)
    tester_traffic_agent(donnees)

if __name__ == "__main__":
    main()