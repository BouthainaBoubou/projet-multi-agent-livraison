"""Génère la carte de mission d'un chauffeur, sur un vrai fond de carte.

Cette carte n'invente rien : elle affiche une décision prise par les
agents. On lui donne la suite de noeuds d'une tournée, elle en tire la
géométrie routière réelle (service `geometrie`) et la dessine sur un fond
OpenStreetMap, avec la feuille de route à côté.

Usage :
    python -m outils.generer_carte_chauffeur --arrets CASA,MRK,AGA
    python -m outils.generer_carte_chauffeur \\
        --arrets CASA,MAD --itineraire CASA,RAB,TNG,TMED,ALG,MAD \\
        --vehicule V001 --cle-api $ORS_KEY

Depuis le 20/08/2026, cette carte est une **vue de rôle** : elle est
destinée au conducteur, elle n'affiche donc que ce qu'un conducteur a le
droit de voir. Le filtrage n'est pas écrit ici — il appartient à
`Commande.vue("conducteur")`, seule autorité sur ce qu'une commande
protège. Une commande sensible n'apparaît que par son identifiant : ni
poids, ni classification, ni client. Un chauffeur transporte un colis,
il n'a pas à savoir ce qu'il transporte ni pour qui.

Tant que `RouteAgent` n'existe pas, l'itinéraire complet est passé à la
main. Le jour où il existe, une seule ligne change dans `main` :
`itineraire = route.itineraire_complet(tournee.sequence)`.
"""

import argparse
import json
import re
from pathlib import Path

from src.agents.route_agent import RouteAgent
from src.data.loader import charger_tout
from src.models.route import ModeTransport
from src.services.geometrie import ServiceGeometrie

NOMS_AFFICHES = {
    "CASA": "Casablanca", "RAB": "Rabat", "KEN": "Kénitra", "TNG": "Tanger",
    "TMED": "Tanger Med", "FES": "Fès", "MEK": "Meknès", "OUJ": "Oujda",
    "MRK": "Marrakech", "AGA": "Agadir", "ESS": "Essaouira",
    "ELJ": "El Jadida", "SAF": "Safi", "BEN": "Béni Mellal",
    "ALG": "Algésiras", "MAD": "Madrid", "VLC": "Valence",
    "BCN": "Barcelone", "PER": "Perpignan", "LYO": "Lyon", "PAR": "Paris",
}

# Rôle auquel cette carte est destinée. Le changer suffirait à tout
# dévoiler : c'est pourquoi il est nommé ici, en clair, et non enfoui
# dans un appel au milieu du fichier.
ROLE_DESTINATAIRE = "conducteur"


def nom_court(id_noeud, par_id):
    """Libellé d'affichage d'un noeud, tolérant aux ajouts dans les CSV."""
    if id_noeud in NOMS_AFFICHES:
        return NOMS_AFFICHES[id_noeud]
    noeud = par_id.get(id_noeud)
    return re.sub(r"\s*\(.*\)", "", noeud.nom) if noeud else id_noeud


def index_troncons(troncons):
    """Indexe les tronçons par paire de noeuds, sans tenir compte du sens."""
    return {frozenset((t.origine, t.destination)): t for t in troncons}


def construire_etapes(donnees, itineraire, service):
    """Assemble, pour chaque étape, le tracé réel et l'état du modèle.

    Deux sources se rejoignent ici : la géométrie vient du calculateur
    d'itinéraire, les chiffres et l'état viennent des données du projet.
    On n'affiche jamais la distance rendue par l'API à la place de celle
    du modèle — c'est le modèle qui fait foi, l'API ne fournit qu'un
    dessin.
    """
    par_paire = index_troncons(donnees.troncons)
    par_id = {n.id: n for n in donnees.noeuds}
    etapes = []

    for depart, arrivee in zip(itineraire, itineraire[1:]):
        troncon = par_paire.get(frozenset((depart, arrivee)))
        if troncon is None:
            raise ValueError(
                f"Aucune liaison entre {depart} et {arrivee} : l'itinéraire "
                f"fourni ne suit pas le réseau"
            )
        trace = service.tracer(depart, arrivee)
        etapes.append({
            "de": nom_court(depart, par_id), "vers": nom_court(arrivee, par_id),
            "points": [[round(lat, 5), round(lon, 5)] for lat, lon in trace.points],
            "approximatif": trace.approximatif,
            "maritime": troncon.mode is ModeTransport.MARITIME,
            "bloquee": troncon.bloquee,
            "congestion": troncon.niveau_trafic,
            "frontiere": troncon.franchit_frontiere,
            "km": troncon.distance_km,
            "minutes": round(troncon.temps_reel_min),
            "attente": troncon.attente_frontiere_min,
        })
    return etapes


def construire_arrets(donnees, arrets, itineraire, role=ROLE_DESTINATAIRE):
    """Prépare la feuille de route : que fait le chauffeur à chaque arrêt.

    Les commandes ne sont pas recopiées champ par champ : on demande à
    chacune la vue correspondant au rôle. C'est la seule façon de
    garantir qu'aucun écran n'oubliera le masquage — il n'existe pas
    d'autre chemin vers la donnée.
    """
    par_id = {n.id: n for n in donnees.noeuds}
    fiches = []

    for rang, id_noeud in enumerate(arrets):
        noeud = par_id[id_noeud]
        a_livrer = [
            c for c in donnees.commandes
            if c.destination == id_noeud and c.origine in arrets
        ]
        fiches.append({
            "rang": rang, "id": id_noeud, "nom": nom_court(id_noeud, par_id),
            "complet": noeud.nom, "type": noeud.type_noeud.name.lower(),
            "lat": noeud.latitude, "lon": noeud.longitude,
            "traitement": noeud.duree_traitement_min,
            "action": "Chargement" if rang == 0 else "Livraison",
            "commandes": [commande.vue(role) for commande in a_livrer],
            "traverse": id_noeud in itineraire,
        })

    # Les noeuds traversés sans arrêt : le chauffeur doit savoir qu'il y
    # passe (péage, port, frontière) même s'il n'y décharge rien.
    for id_noeud in itineraire:
        if id_noeud in arrets:
            continue
        noeud = par_id[id_noeud]
        fiches.append({
            "rang": None, "id": id_noeud, "nom": nom_court(id_noeud, par_id),
            "complet": noeud.nom, "type": noeud.type_noeud.name.lower(),
            "lat": noeud.latitude, "lon": noeud.longitude,
            "traitement": noeud.duree_traitement_min,
            "action": "Passage", "commandes": [], "traverse": True,
        })

    # Remettre les fiches dans l'ordre du trajet, arrêts et simples
    # passages mélangés. Sans ce tri, les noeuds traversés sans arrêt se
    # retrouvent tous en fin de liste : le chauffeur lit « Perpignan »,
    # puis « Tanger Med » — c'est-à-dire l'inverse de ce qu'il va vivre.
    # La numérotation des arrêts, elle, ne bouge pas : un passage n'est
    # pas un arrêt, il reste sans numéro.
    position_dans_itineraire: dict[str, int] = {}
    for position, id_noeud in enumerate(itineraire):
        position_dans_itineraire.setdefault(id_noeud, position)
    fiches.sort(
        key=lambda fiche: position_dans_itineraire.get(fiche["id"], len(itineraire))
    )
    return fiches


GABARIT = """<!DOCTYPE html>
<html lang="fr">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Mission __VEHICULE__ — feuille de route</title>
<link rel="stylesheet" href="https://cdnjs.cloudflare.com/ajax/libs/leaflet/1.9.4/leaflet.min.css">
<style>
  :root {
    color-scheme: light;
    --page: #f9f9f7; --surface: #fcfcfb;
    --ink-1: #0b0b0b; --ink-2: #52514e; --muted: #898781;
    --hairline: #e1e0d9; --anneau: rgba(11,11,11,0.10);
    --hub: #2a78d6; --agence: #1baf7a; --port: #eb6834;
    --route: #2a78d6; --congestion: #fab219; --bloque: #d03b3b;
    --fragile: #a4622a; --confidentiel: #6b6a66;
  }
  * { box-sizing: border-box; }
  body {
    margin: 0; background: var(--page); color: var(--ink-1);
    font: 14px/1.5 system-ui, -apple-system, "Segoe UI", sans-serif;
    display: flex; height: 100vh; overflow: hidden;
  }
  #carte { flex: 1 1 auto; height: 100%; background: var(--surface); }
  aside {
    flex: 0 0 340px; height: 100%; overflow-y: auto; padding: 18px 20px;
    background: var(--surface); border-left: 1px solid var(--anneau);
  }
  h1 { font-size: 17px; margin: 0 0 2px; }
  .sous { color: var(--ink-2); font-size: 12.5px; margin: 0 0 16px; }
  h2 {
    font-size: 11px; text-transform: uppercase; letter-spacing: 0.07em;
    color: var(--muted); margin: 20px 0 8px; font-weight: 600;
  }
  .resume { display: flex; gap: 20px; padding: 12px 0; border-top: 1px solid var(--hairline); border-bottom: 1px solid var(--hairline); }
  .resume b { display: block; font-size: 19px; font-weight: 600; line-height: 1.2; }
  .resume span { font-size: 11px; color: var(--muted); }
  ol { list-style: none; margin: 0; padding: 0; }
  li { display: flex; gap: 11px; padding: 9px 0; border-bottom: 1px solid var(--hairline); }
  .pastille {
    flex: none; width: 23px; height: 23px; border-radius: 50%;
    display: grid; place-items: center; font-size: 11.5px; font-weight: 600;
    background: var(--hub); color: #fff; margin-top: 2px;
  }
  .pastille.passage { background: transparent; color: var(--muted); border: 1.5px dashed var(--muted); }
  .pastille.port { background: var(--port); }
  .nom { font-weight: 600; }
  .meta { color: var(--ink-2); font-size: 12.5px; }
  .cmd { color: var(--muted); font-size: 12px; }
  .cmd .fragile { color: var(--fragile); font-weight: 600; }
  .cmd .confidentiel { color: var(--confidentiel); font-style: italic; }
  .avert {
    background: rgba(250,178,25,0.14); border: 1px solid rgba(250,178,25,0.5);
    border-radius: 7px; padding: 9px 11px; font-size: 12.5px; color: var(--ink-2);
    margin-bottom: 14px;
  }
  .legende { font-size: 12.5px; color: var(--ink-2); }
  .legende div { display: flex; align-items: center; gap: 8px; margin: 5px 0; }
  .trait { width: 22px; height: 0; border-top-width: 3px; border-top-style: solid; }
</style>
</head>
<body>
<div id="carte"></div>
<aside>
  <h1>Mission __VEHICULE__</h1>
  <p class="sous">__RESUME_TEXTE__</p>
  <div id="avertissement"></div>

  <div class="resume">
    <div><b>__KM__</b><span>km</span></div>
    <div><b>__DUREE__</b><span>de trajet</span></div>
    <div><b>__NB_ARRETS__</b><span>arrêts</span></div>
  </div>

  <h2>Feuille de route</h2>
  <ol id="feuille"></ol>

  <h2>Légende</h2>
  <div class="legende">
    <div><span class="trait" style="border-color:var(--route)"></span> Route à suivre</div>
    <div><span class="trait" style="border-color:var(--congestion)"></span> Tronçon congestionné</div>
    <div><span class="trait" style="border-color:var(--port);border-top-style:dashed"></span> Traversée maritime</div>
    <div><span class="trait" style="border-color:var(--bloque);border-top-style:dashed"></span> Tronçon bloqué</div>
  </div>
</aside>

<script src="https://cdnjs.cloudflare.com/ajax/libs/leaflet/1.9.4/leaflet.min.js"></script>
<script>
const ETAPES = __ETAPES__;
const ARRETS = __ARRETS__;

/* La bibliothèque de carte et le fond de plan viennent d'Internet ; le
   tracé et la feuille de route, non — ils sont dans ce fichier. Un
   chauffeur hors couverture réseau doit garder sa feuille de route
   lisible : on la construit d'abord, la carte ensuite, et l'absence de
   carte ne fait pas tomber la page. */
const carteDisponible = typeof L !== "undefined";

function styleEtape(e) {
  if (e.bloquee) return { color: "#d03b3b", dashArray: "6 6", weight: 5 };
  if (e.maritime) return { color: "#eb6834", dashArray: "8 7", weight: 4 };
  if (e.congestion >= 1.2) return { color: "#fab219", weight: 6 };
  return { color: "#2a78d6", weight: 5 };
}

/* Les commandes arrivent déjà filtrées par le modèle : cette page ne
   voit jamais le poids ni la classification d'un lot confidentiel, elle
   ne peut donc pas les afficher par accident. Elle se contente de
   mettre en forme ce qu'on lui a laissé. */
function libelleCommande(c) {
  if (c.confidentiel) return `${c.id} — <span class="confidentiel">contenu confidentiel</span>`;
  const mention =
    c.fragilite === "tres_fragile" ? ` · <span class="fragile">TRÈS FRAGILE</span>`
    : c.fragilite === "fragile" ? ` · <span class="fragile">fragile</span>`
    : "";
  return `${c.id} — ${c.poids} kg${mention}`;
}

function libelleCommandeTexte(c) {
  if (c.confidentiel) return `${c.id} — contenu confidentiel`;
  const mention =
    c.fragilite === "tres_fragile" ? " · TRÈS FRAGILE"
    : c.fragilite === "fragile" ? " · fragile" : "";
  return `${c.id} — ${c.poids} kg${mention}`;
}

const COULEURS = { hub: "#2a78d6", agence: "#1baf7a", port: "#eb6834", client: "#52514e" };
const approximatifs = ETAPES.filter(e => e.approximatif && !e.maritime).length;
let carte = null;

/* 1. La feuille de route, toujours. */
const feuille = document.getElementById("feuille");
for (const a of ARRETS) {
  const estArret = a.rang !== null;
  const li = document.createElement("li");
  li.innerHTML =
    `<div class="pastille ${estArret ? (a.type === "port" ? "port" : "") : "passage"}">` +
    `${estArret ? a.rang + 1 : "·"}</div><div>` +
    `<div class="nom">${a.nom}</div>` +
    `<div class="meta">${a.action} · ${a.traitement} min sur place</div>` +
    (a.commandes.length
      ? `<div class="cmd">${a.commandes.map(libelleCommande).join("<br>")}</div>`
      : "") +
    `</div>`;
  li.addEventListener("click", () => { if (carte) carte.setView([a.lat, a.lon], 11); });
  feuille.appendChild(li);
}

/* 2. La carte, si la bibliothèque a pu être chargée. */
if (!carteDisponible) {
  document.getElementById("carte").innerHTML =
    `<div style="padding:28px;color:var(--ink-2);max-width:44ch">` +
    `<b>Fond de carte indisponible</b><br>La page n'a pas pu joindre le ` +
    `réseau. La feuille de route ci-contre reste complète et exacte : ` +
    `elle ne dépend d'aucune ressource externe.</div>`;
} else {
  carte = L.map("carte", { zoomControl: true });
  L.tileLayer("https://tile.openstreetmap.org/{z}/{x}/{y}.png", {
    maxZoom: 18, attribution: "&copy; OpenStreetMap",
  }).addTo(carte);

  const tous = [];
  for (const e of ETAPES) {
    const style = styleEtape(e);
    if (e.approximatif && !e.maritime) style.dashArray = "3 8";
    const ligne = L.polyline(e.points, { ...style, opacity: 0.9 }).addTo(carte);
    ligne.bindPopup(
      `<b>${e.de} → ${e.vers}</b><br>${e.km} km · ${e.minutes} min` +
      (e.congestion > 1 ? `<br>Congestion × ${e.congestion.toFixed(1)}` : "") +
      (e.attente > 0 ? `<br>Attente frontière ${e.attente} min` : "") +
      (e.approximatif && !e.maritime ? "<br><i>tracé approximatif</i>" : "")
    );
    tous.push(...e.points);
  }

  for (const a of ARRETS) {
    const estArret = a.rang !== null;
    const marqueur = L.circleMarker([a.lat, a.lon], {
      radius: estArret ? 10 : 6,
      fillColor: COULEURS[a.type] || "#52514e",
      color: "#fff", weight: 2, fillOpacity: 1,
    }).addTo(carte);
    const lignes = a.commandes.map(libelleCommandeTexte);
    marqueur.bindPopup(
      `<b>${a.complet}</b><br>${a.action}<br>Immobilisation ${a.traitement} min` +
      (lignes.length ? "<br>" + lignes.join("<br>") : "")
    );
    if (estArret) {
      marqueur.bindTooltip(String(a.rang + 1), {
        permanent: true, direction: "center", className: "num",
      });
    }
  }

  carte.fitBounds(L.latLngBounds(tous), { padding: [40, 40] });
}

if (approximatifs > 0) {
  document.getElementById("avertissement").innerHTML =
    `<div class="avert"><b>${approximatifs} tronçon(s) en tracé approximatif.</b> ` +
    `La géométrie routière réelle n'a pas pu être récupérée — les segments ` +
    `concernés sont dessinés en pointillés fins. Relancez le générateur avec ` +
    `une clé d'API pour compléter le cache.</div>`;
}
</script>
</body>
</html>
"""


def main() -> None:
    analyseur = argparse.ArgumentParser(description=__doc__)
    analyseur.add_argument("--arrets", default="CASA,MRK,AGA",
                           help="identifiants des arrêts, séparés par des virgules")
    analyseur.add_argument("--itineraire", default=None,
                           help="tous les noeuds traversés (défaut : calculé "
                                "par le RouteAgent à partir des arrêts)")
    analyseur.add_argument("--vehicule", default="V001")
    analyseur.add_argument("--cle-api", default=None,
                           help="clé OpenRouteService ; sans elle, tracés approximatifs")
    analyseur.add_argument("--fournisseur", default="ors", choices=["ors", "osrm"])
    analyseur.add_argument("--sortie", default="carte_chauffeur.html")
    options = analyseur.parse_args()

    donnees = charger_tout("data")
    arrets = options.arrets.split(",")
    if options.itineraire:
        itineraire = options.itineraire.split(",")
    else:
        # Deux arrêts qui se suivent dans une tournée ne sont pas
        # forcément voisins sur le réseau : Kénitra et Marrakech n'ont
        # aucune liaison directe. Le chemin entre eux n'est plus à
        # déplier à la main — on le demande au `RouteAgent`, la même
        # autorité que celle qui a calculé le plan. C'est aussi ce qui
        # garantit que la carte respecte les tronçons bloqués.
        itineraire = RouteAgent(
            donnees.noeuds, donnees.troncons
        ).itineraire_complet(arrets)

    service = ServiceGeometrie(
        donnees.noeuds, donnees.troncons,
        cle_api=options.cle_api, fournisseur=options.fournisseur,
    )
    etapes = construire_etapes(donnees, itineraire, service)
    service.sauver_cache()

    fiches = construire_arrets(donnees, arrets, itineraire)
    par_id = {n.id: n for n in donnees.noeuds}
    resume_texte = (
        f"{nom_court(arrets[0], par_id)} → {nom_court(arrets[-1], par_id)}, "
        f"itinéraire calculé par les agents"
    )
    km = round(sum(e["km"] for e in etapes))
    minutes = sum(e["minutes"] for e in etapes)
    duree = f"{minutes // 60} h {minutes % 60:02d}"

    page = (
        GABARIT
        .replace("__VEHICULE__", options.vehicule)
        .replace("__RESUME_TEXTE__", resume_texte)
        .replace("__KM__", str(km))
        .replace("__DUREE__", duree)
        .replace("__NB_ARRETS__", str(len(arrets)))
        .replace("__ETAPES__", json.dumps(etapes, ensure_ascii=False))
        .replace("__ARRETS__", json.dumps(fiches, ensure_ascii=False))
    )

    Path(options.sortie).write_text(page, encoding="utf-8")
    approx = sum(1 for e in etapes if e["approximatif"] and not e["maritime"])
    confidentielles = sum(
        1 for fiche in fiches for commande in fiche["commandes"]
        if commande.get("confidentiel")
    )
    print(f"Carte écrite : {options.sortie}")
    print(f"{len(etapes)} étapes, {km} km, {duree} — "
          f"{service.appels_reseau} appel(s) réseau, {approx} tracé(s) approximatif(s)")
    if confidentielles:
        print(f"{confidentielles} commande(s) affichée(s) sans détail "
              f"(confidentialité), rôle « {ROLE_DESTINATAIRE} »")


if __name__ == "__main__":
    main()