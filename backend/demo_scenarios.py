from src.agents.coordinator_agent import CoordinatorAgent
from src.data.loader import charger_tout


def titre(texte: str) -> None:
    print(f"\n{'=' * 74}\n{texte}\n{'=' * 74}")


coordinateur = CoordinatorAgent(charger_tout("data"))

titre("PLANIFICATION INITIALE")
coordinateur.planifier()
print(coordinateur.resume())

exemple = coordinateur.plan.tournees[0]
print(
    f"\nItinéraire détaillé de {exemple.vehicule_id} : "
    f"{' → '.join(coordinateur.itineraire(exemple))}"
)
reference = coordinateur.score()["Z"]

titre("SCÉNARIO 1 — pic de congestion sur Casablanca – Marrakech (× 2,2)")
coordinateur.declarer_congestion("CASA", "MRK", 2.2)
print(coordinateur.resume())
coordinateur.declarer_congestion("CASA", "MRK", 1.1)      # retour au nominal

titre("SCÉNARIO 2 — panne d'un véhicule chargé")
en_panne = coordinateur.plan.tournees[0].vehicule_id
print(f"Véhicule mis en panne : {en_panne}\n")
coordinateur.declarer_panne(en_panne)
print(coordinateur.resume())
coordinateur.declarer_reparation(en_panne)

titre("SCÉNARIO 3 — blocage du ferry Tanger Med – Algésiras")
coordinateur.declarer_blocage("TMED", "ALG")
print(coordinateur.resume())
coordinateur.declarer_deblocage("TMED", "ALG")

titre("SCÉNARIO 4 — 5 h d'attente au franchissement du détroit")
coordinateur.declarer_attente_frontiere("TMED", "ALG", 300)
print(coordinateur.resume())
coordinateur.declarer_attente_frontiere("TMED", "ALG", 120)

titre("JOURNAL DES DÉCISIONS")
print(coordinateur.journal_texte())
print(f"\nZ de référence (réseau nominal) : {reference}")
print(f"Z après retour au nominal        : {coordinateur.score()['Z']}")