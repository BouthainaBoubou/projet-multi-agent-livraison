"""Contrôle des fichiers du projet : présence, version, contrat de données.

Ce script ne fait tourner aucun agent. Il répond à une seule question,
celle qu'on se pose après avoir copié des fichiers : **est-ce que j'ai
bien la bonne version de chaque fichier ?**

Trois contrôles, du plus faible au plus fort :

1. **présence** — le fichier est là ;
2. **marqueurs attendus** — il contient des bouts de code qui n'existent
   que dans la version du 20/08. Un fichier resté à l'ancienne version
   est détecté même s'il porte le bon nom ;
3. **marqueurs interdits** — il ne contient plus de trace de l'ancienne
   version. C'est ce contrôle qui attrape une fusion à moitié faite.

Pour les CSV, les colonnes exigées **ne sont pas recopiées ici** : elles
sont importées du loader. C'est ce qui empêche ce script de se
désynchroniser du code — l'erreur qu'il a justement pour métier d'éviter.

    python verif_fichiers.py
"""

import csv
import json
from pathlib import Path

from src.data.loader import (
    COLONNES_COMMANDES, COLONNES_NOEUDS, COLONNES_TRONCONS,
    COLONNES_UTILISATEURS, COLONNES_VEHICULES,
)
from src.models.commande import CRITERES_CLASSIFICATION

# --- Fichiers dont on sait exactement ce qu'ils doivent contenir ---
#
# Un marqueur est une chaîne courte et caractéristique de la version
# attendue. On ne compare pas des fichiers entiers : ils changent à
# chaque commentaire. On vérifie que les décisions du 20/08 sont bien là.
MARQUEURS: dict[str, list[str]] = {
    # Modèle
    "src/models/noeud.py": ["class TypeNoeud", "est_point_de_passage"],
    "src/models/route.py": ["class ProfilTrafic", "COEFFICIENTS_HORAIRES",
                            "def trafic_a"],
    "src/models/commande.py": ["GRILLE_PRIORITE", "class Fragilite",
                               "class Confidentialite", "CRITERES_CLASSIFICATION",
                               "def vue", "INCOMPLETE"],
    "src/models/vehicule.py": ["equipement_fragile", "def accepte_fragilite",
                               "modele"],
    "src/models/tournee.py": ["risque_fragilite", "def risque_total"],
    # Chargement
    "src/data/loader.py": ["_critere_lu", "profil_trafic", "equipement_fragile",
                           "commandes_incompletes", "charger_comptes"],
    # Sécurité
    "src/securite/authentification.py": ["pbkdf2_hmac", "compare_digest",
                                         "exiger_acces_tournee", "class Role",
                                         "TENTATIVES_MAX"],
    # Agents
    "src/agents/order_agent.py": ["completer_commande", "modifier_commande",
                                  "criteres_attendus", "STATUTS_MODIFIABLES"],
    "src/agents/vehicle_agent.py": ["peut_transporter_fragilite",
                                    "vehicules_equipes_fragile"],
    "src/agents/traffic_agent.py": ["appliquer_profil_horaire",
                                    "heure_appliquee"],
    "src/agents/route_agent.py": ["class CheminIntrouvable", "itineraire_complet"],
    "src/agents/optimization_agent.py": ["_commande_saturee", "_manutentions",
                                         "self.epsilon"],
    "src/agents/coordinator_agent.py": ["CommandesIncompletes",
                                        "definir_heure_depart",
                                        "feuille_de_route",
                                        "commandes_a_completer"],
    # Outils
    "outils/generer_carte_chauffeur.py": ["ROLE_DESTINATAIRE",
                                          "itineraire_complet",
                                          "libelleCommande"],
    "outils/creer_utilisateur.py": ["getpass", "demander_mot_de_passe"],
    # Contrôles
    "verif_criteres.py": ["CommandesIncompletes", "critères d'acceptation"],
    "verif_securite.py": ["exiger_acces_tournee", "critères d'acceptation"],
}

# Traces de l'ancienne version qui ne doivent plus exister nulle part.
# Elles attrapent le cas le plus sournois : un dossier à moitié mis à
# jour, où tout se charge mais où deux fichiers ne se parlent plus.
INTERDITS: dict[str, list[str]] = {
    "src/data/loader.py": ["priorite=Priorite["],
    "src/models/commande.py": ["priorite: Priorite"],
}

# Fichiers dont on vérifie seulement la présence : ils n'ont pas été
# touchés le 20/08, leur contenu ne prouve donc aucune version.
PRESENCE_SEULE: list[str] = [
    "src/services/geometrie.py",
    "outils/generer_carte.py",
    "outils/preparer_cache.py",
    "demo_scenarios.py",
    "verif_chargement.py",
    "verif_agents.py",
]

INITS: list[str] = [
    "src/__init__.py",
    "src/models/__init__.py",
    "src/data/__init__.py",
    "src/agents/__init__.py",
    "src/securite/__init__.py",
    "src/services/__init__.py",
    "outils/__init__.py",
]

# Le contrat de colonnes vient du loader : aucune liste n'est recopiée.
CONTRATS_CSV: dict[str, set[str]] = {
    "data/noeuds.csv": COLONNES_NOEUDS,
    "data/commandes.csv": COLONNES_COMMANDES,
    "data/vehicules.csv": COLONNES_VEHICULES,
    "data/routes.csv": COLONNES_TRONCONS,
    "data/utilisateurs.csv": COLONNES_UTILISATEURS,
}

# Longueurs attendues en hexadécimal : SHA-256 rend 32 octets, le sel en
# fait 16. Une valeur plus courte trahirait un fichier bricolé à la main.
LONGUEUR_EMPREINTE_HEX = 64
LONGUEUR_SEL_HEX = 32

problemes: list[str] = []


def signaler(chemin: str, etat: str, detail: str = "") -> None:
    """Affiche une ligne de résultat et retient les problèmes."""
    print(f"  {etat:<9} {chemin}" + (f"   {detail}" if detail else ""))
    if etat == "PROBLEME":
        problemes.append(chemin)


def controler_code(chemin: str) -> None:
    """Présence, marqueurs attendus, marqueurs interdits."""
    fichier = Path(chemin)
    if not fichier.is_file():
        signaler(chemin, "PROBLEME", "fichier absent")
        return

    contenu = fichier.read_text(encoding="utf-8")

    manquants = [m for m in MARQUEURS.get(chemin, []) if m not in contenu]
    if manquants:
        signaler(
            chemin, "PROBLEME",
            f"ancienne version : marqueur(s) absent(s) {manquants}",
        )
        return

    restes = [m for m in INTERDITS.get(chemin, []) if m in contenu]
    if restes:
        signaler(
            chemin, "PROBLEME",
            f"reste de l'ancienne version : {restes}",
        )
        return

    signaler(chemin, "OK")


def controler_presence(chemin: str, note: str = "") -> None:
    """Le fichier est là, son contenu n'est pas jugé."""
    if Path(chemin).is_file():
        signaler(chemin, "OK", note)
    else:
        signaler(chemin, "PROBLEME", "fichier absent")


def colonnes_du_csv(chemin: Path) -> list[str]:
    """En-tête d'un CSV, sans charger tout le fichier."""
    with chemin.open(encoding="utf-8", newline="") as flux:
        entete = next(csv.reader(flux), [])
    return [colonne.strip() for colonne in entete]


def controler_csv(chemin: str, exigees: set[str]) -> None:
    """Le fichier contient au moins les colonnes exigées par le loader.

    Les colonnes en trop ne sont pas une erreur : le loader les ignore,
    et c'est ce qui permet de garder une colonne `description` pour la
    lisibilité humaine.
    """
    fichier = Path(chemin)
    if not fichier.is_file():
        signaler(chemin, "PROBLEME", "fichier absent")
        return

    colonnes = colonnes_du_csv(fichier)
    manquantes = sorted(exigees - set(colonnes))
    if manquantes:
        signaler(chemin, "PROBLEME", f"colonnes manquantes : {manquantes}")
        return
    signaler(chemin, "OK", f"{len(colonnes)} colonnes")


def controler_commandes() -> None:
    """Contrôle propre aux critères de classification.

    Ces quatre colonnes sont **facultatives**, et c'est voulu : une
    commande à qui il manque un critère doit pouvoir être chargée, pour
    que le dispatcheur puisse la compléter à l'écran. Leur absence n'est
    donc jamais une erreur — elle est simplement comptée, pour qu'on
    sache combien de saisies attendent avant de pouvoir planifier.
    """
    fichier = Path("data/commandes.csv")
    if not fichier.is_file():
        return

    colonnes = colonnes_du_csv(fichier)

    if "priorite" in colonnes:
        signaler(
            "data/commandes.csv", "PROBLEME",
            "la colonne 'priorite' subsiste : elle est désormais calculée "
            "par la grille de classification et serait ignorée",
        )
        return

    presents = [c for c in CRITERES_CLASSIFICATION if c in colonnes]
    absents = [c for c in CRITERES_CLASSIFICATION if c not in colonnes]

    with fichier.open(encoding="utf-8", newline="") as flux:
        lignes = list(csv.DictReader(flux))
    a_completer = [
        ligne["id"] for ligne in lignes
        if any(not (ligne.get(c) or "").strip() for c in CRITERES_CLASSIFICATION)
    ]

    detail = f"{len(presents)}/4 critères présents"
    if absents:
        detail += f", absents : {absents}"
    if a_completer:
        apercu = ", ".join(a_completer[:5])
        suite = "…" if len(a_completer) > 5 else ""
        detail += (
            f" — {len(a_completer)} commande(s) à compléter à la main "
            f"({apercu}{suite})"
        )
    else:
        detail += " — les 28 commandes sont classées"
    signaler("critères de classification", "OK", detail)


def controler_utilisateurs() -> None:
    """Le fichier des comptes ne doit contenir aucun mot de passe.

    Contrôle de forme, pas de confiance : on ne se demande pas si
    quelqu'un a *voulu* écrire un mot de passe, on vérifie que chaque
    ligne a bien la forme d'une empreinte salée. Une colonne suspecte,
    un sel trop court, un nombre d'itérations abaissé — les trois façons
    d'affaiblir le fichier sans que rien ne cesse de fonctionner.
    """
    fichier = Path("data/utilisateurs.csv")
    if not fichier.is_file():
        return

    colonnes = colonnes_du_csv(fichier)
    suspectes = [
        colonne for colonne in colonnes
        if any(mot in colonne.lower() for mot in ("passe", "password", "clair"))
    ]
    if suspectes:
        signaler(
            "comptes", "PROBLEME",
            f"colonne(s) suspecte(s) {suspectes} : un mot de passe ne "
            f"s'écrit nulle part",
        )
        return

    with fichier.open(encoding="utf-8", newline="") as flux:
        lignes = list(csv.DictReader(flux))

    for ligne in lignes:
        identifiant = ligne["identifiant"]
        if len(ligne["empreinte"]) != LONGUEUR_EMPREINTE_HEX:
            signaler(
                "comptes", "PROBLEME",
                f"{identifiant} : empreinte de {len(ligne['empreinte'])} "
                f"caractères, attendu {LONGUEUR_EMPREINTE_HEX}",
            )
            return
        if len(ligne["sel"]) != LONGUEUR_SEL_HEX:
            signaler(
                "comptes", "PROBLEME",
                f"{identifiant} : sel de {len(ligne['sel'])} caractères, "
                f"attendu {LONGUEUR_SEL_HEX}",
            )
            return
        if int(ligne["iterations"]) < 100_000:
            signaler(
                "comptes", "PROBLEME",
                f"{identifiant} : {ligne['iterations']} itérations, "
                f"c'est trop peu pour résister à une attaque hors ligne",
            )
            return

    sels = [ligne["sel"] for ligne in lignes]
    if len(set(sels)) != len(sels):
        signaler(
            "comptes", "PROBLEME",
            "deux comptes partagent le même sel : une table précalculée "
            "les casserait tous les deux d'un coup",
        )
        return

    roles = [ligne["role"] for ligne in lignes]
    signaler(
        "comptes", "OK",
        f"{len(lignes)} compte(s) — {roles.count('dispatcheur')} dispatcheur, "
        f"{roles.count('conducteur')} conducteur(s), aucun mot de passe stocké",
    )


def controler_cache() -> None:
    """Le cache de géométrie est présent, lisible, et non vidé.

    Il représente 27 appels à une API externe : le perdre coûte une
    reconstruction complète. Mieux vaut le voir compté à chaque contrôle.
    """
    fichier = Path("data/geometries.json")
    if not fichier.is_file():
        signaler("data/geometries.json", "PROBLEME", "fichier absent")
        return
    try:
        donnees = json.loads(fichier.read_text(encoding="utf-8"))
    except json.JSONDecodeError as erreur:
        signaler("data/geometries.json", "PROBLEME", f"JSON illisible : {erreur}")
        return

    entrees = len(donnees)
    approximatifs = sum(
        1 for valeur in donnees.values()
        if isinstance(valeur, dict) and valeur.get("approximatif")
    )
    total = _nombre_de_troncons()
    detail = (
        f"{entrees} tronçon(s) mémorisé(s), {entrees - approximatifs} "
        f"en géométrie réelle"
    )
    if total:
        detail += f", sur {total} tronçons du réseau"
    signaler("data/geometries.json", "OK", detail)


def _nombre_de_troncons() -> int:
    """Nombre de lignes de routes.csv, ou 0 si le fichier manque."""
    fichier = Path("data/routes.csv")
    if not fichier.is_file():
        return 0
    with fichier.open(encoding="utf-8", newline="") as flux:
        return sum(1 for _ in csv.DictReader(flux))


def main() -> int:
    print("--- Fichiers de code (présence + version) ---")
    for chemin in MARQUEURS:
        controler_code(chemin)

    print("--- Fichiers inchangés le 20/08 (présence seule) ---")
    for chemin in PRESENCE_SEULE:
        controler_presence(chemin)

    print("--- Fichiers __init__.py ---")
    for chemin in INITS:
        controler_presence(chemin)

    print("--- Données ---")
    for chemin, exigees in CONTRATS_CSV.items():
        controler_csv(chemin, exigees)
    controler_commandes()
    controler_utilisateurs()
    controler_cache()

    print("-" * 70)
    if problemes:
        print(f"{len(problemes)} problème(s) à corriger :")
        for chemin in problemes:
            print(f"  - {chemin}")
        return 1
    print("Tous les fichiers sont présents et à la version du 20/08/2026.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())