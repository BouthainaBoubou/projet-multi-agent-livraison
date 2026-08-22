import json
import re
from math import cos, radians
from pathlib import Path

from src.agents.route_agent import CheminIntrouvable, RouteAgent
from src.data.loader import charger_tout
from src.models.noeud import TypeNoeud
from src.models.route import ModeTransport

# Les CSV sont volontairement sans accents (robustesse de l'encodage) :
# l'accentuation est une question de présentation, elle appartient à cette
# couche et pas aux données.
NOMS_AFFICHES = {
    "CASA": "Casablanca", "RAB": "Rabat", "KEN": "Kénitra", "TNG": "Tanger",
    "TMED": "Tanger Med", "FES": "Fès", "MEK": "Meknès", "OUJ": "Oujda",
    "MRK": "Marrakech", "AGA": "Agadir", "ESS": "Essaouira",
    "ELJ": "El Jadida", "SAF": "Safi", "BEN": "Béni Mellal",
    "ALG": "Algésiras", "MAD": "Madrid", "VLC": "Valence",
    "BCN": "Barcelone", "PER": "Perpignan", "LYO": "Lyon", "PAR": "Paris",
}



def nom_court(id_noeud, par_id):
    """Libellé d'affichage d'un noeud.

    Le dictionnaire ci-dessus ne sert qu'à accentuer les noms connus. Un
    noeud ajouté aux CSV sans y figurer n'est pas une erreur : on retombe
    sur son nom, débarrassé de sa parenthèse. La carte ne doit jamais
    casser parce qu'une ville a été ajoutée aux données.
    """
    if id_noeud in NOMS_AFFICHES:
        return NOMS_AFFICHES[id_noeud]
    noeud = par_id.get(id_noeud)
    return re.sub(r"\s*\(.*\)", "", noeud.nom) if noeud else id_noeud


def vues_par_defaut(donnees):
    """Déduit les deux vues des données, sans aucune liste en dur.

    La vue nationale, c'est le pays du hub. La vue corridor, c'est
    l'ensemble des chemins qui mènent du hub à chaque noeud étranger —
    calculés, pas énumérés. Ajouter Oujda ou Séville aux CSV suffit à les
    voir apparaître sur la bonne carte.
    """
    hub = next(
        (n for n in donnees.noeuds if n.type_noeud is TypeNoeud.HUB),
        donnees.noeuds[0],
    )
    nationale = [n.id for n in donnees.noeuds if n.pays == hub.pays]
    etrangers = [n.id for n in donnees.noeuds if n.pays != hub.pays]

    route = RouteAgent(donnees.noeuds, donnees.troncons)
    corridor = {hub.id}
    for identifiant in etrangers:
        try:
            corridor.update(route.plus_court_chemin(hub.id, identifiant))
        except CheminIntrouvable:
            corridor.add(identifiant)

    return nationale, sorted(corridor)


# Placement des étiquettes, par vue : ancrage ("l" ou "r") et décalage
# manuel en pixels. Les noeuds du détroit sont trop proches à l'échelle du
# corridor pour être séparés automatiquement.
ETIQUETTES = {
    "nationale": {
        "CASA": ("l", 0, 4), "RAB": ("r", 2, -6), "KEN": ("r", 0, 4),
        "TNG": ("l", 0, 6), "TMED": ("r", 0, -4), "FES": ("r", 0, 2),
        "MEK": ("l", 0, -6), "OUJ": ("l", 0, -10), "MRK": ("l", 0, 2),
        "AGA": ("r", 0, 8), "ESS": ("l", 0, 2), "ELJ": ("l", 0, 6),
        "SAF": ("l", 0, 0), "BEN": ("r", 0, 6),
    },
    "corridor": {
        "CASA": ("r", 0, 6), "RAB": ("l", 0, 2), "TNG": ("l", 0, -6),
        "TMED": ("l", 0, 12), "ALG": ("r", 2, 0), "MAD": ("l", 0, 0),
        "VLC": ("r", 0, 6), "BCN": ("r", 0, 0), "PER": ("l", 0, -4),
        "LYO": ("r", 0, 0), "PAR": ("r", 0, 0),
    },
}

# Marge horizontale plus large que la verticale : les étiquettes des noeuds
# extrêmes (Essaouira à l'ouest, Oujda à l'est) débordent latéralement.
MARGE_X = 88
MARGE_Y = 46
HAUTEUR_UTILE = 520


def projeter(noeuds, hauteur_utile=HAUTEUR_UTILE):
    """Projette des coordonnées GPS en pixels (équirectangulaire).

    La longitude est corrigée par le cosinus de la latitude moyenne : sans
    cette correction, la carte est étirée en largeur et le Maroc paraît
    beaucoup plus large qu'il ne l'est.
    """
    lats = [n.latitude for n in noeuds]
    lons = [n.longitude for n in noeuds]
    lat_min, lat_max = min(lats), max(lats)
    lon_min, lon_max = min(lons), max(lons)
    # Une vue réduite à un seul noeud aurait une étendue nulle : on lui
    # donne une largeur minimale plutôt que de diviser par zéro.
    lat_max = max(lat_max, lat_min + 0.05)
    lon_max = max(lon_max, lon_min + 0.05)
    facteur = cos(radians((lat_min + lat_max) / 2))
    echelle = hauteur_utile / (lat_max - lat_min)

    positions = {
        n.id: (
            MARGE_X + (n.longitude - lon_min) * facteur * echelle,
            MARGE_Y + (lat_max - n.latitude) * echelle,
        )
        for n in noeuds
    }
    largeur = (lon_max - lon_min) * facteur * echelle + 2 * MARGE_X
    return positions, round(largeur), round(hauteur_utile + 2 * MARGE_Y)


def construire_vue(donnees, cle_vue, ids_retenus, hauteur_utile):
    """Prépare les noeuds et liaisons projetés d'une des deux vues."""
    par_id = {n.id: n for n in donnees.noeuds}
    retenus = [n for n in donnees.noeuds if n.id in ids_retenus]
    positions, largeur, hauteur = projeter(retenus, hauteur_utile)
    etiquettes = ETIQUETTES.get(cle_vue, {})

    commandes_par_destination = {}
    for commande in donnees.commandes:
        commandes_par_destination[commande.destination] = (
            commandes_par_destination.get(commande.destination, 0) + 1
        )

    noeuds = []
    for noeud in retenus:
        ancrage, dx, dy = etiquettes.get(noeud.id, ("r", 0, 0))
        x, y = positions[noeud.id]
        noeuds.append({
            "id": noeud.id, "nom": nom_court(noeud.id, par_id),
            "complet": noeud.nom, "pays": noeud.pays,
            "type": noeud.type_noeud.name, "x": round(x, 1), "y": round(y, 1),
            "traitement": noeud.duree_traitement_min,
            "ancrage": ancrage, "dx": dx, "dy": dy,
            "commandes": commandes_par_destination.get(noeud.id, 0),
        })

    liaisons = []
    for troncon in donnees.troncons:
        if troncon.origine not in positions or troncon.destination not in positions:
            continue
        xa, ya = positions[troncon.origine]
        xb, yb = positions[troncon.destination]
        liaisons.append({
            "a": troncon.origine, "b": troncon.destination,
            "na": nom_court(troncon.origine, par_id),
            "nb": nom_court(troncon.destination, par_id),
            "x1": round(xa, 1), "y1": round(ya, 1),
            "x2": round(xb, 1), "y2": round(yb, 1),
            "km": troncon.distance_km, "base": troncon.temps_base_min,
            "trafic": troncon.niveau_trafic,
            "attente": troncon.attente_frontiere_min,
            "reel": round(troncon.temps_reel_min),
            "cout": troncon.cout_fixe_dh,
            "maritime": troncon.mode is ModeTransport.MARITIME,
            "frontiere": troncon.franchit_frontiere,
        })

    return {
        "noeuds": noeuds, "liaisons": liaisons,
        "largeur": largeur, "hauteur": hauteur,
    }


def construire_graphe_complet(donnees):
    """Liste d'arêtes du réseau entier, pour le calcul d'accessibilité.

    L'accessibilité se calcule sur le graphe complet, pas sur la vue :
    couper le ferry rend Madrid inaccessible même si on regarde la carte
    du Maroc.
    """
    return [
        {"a": t.origine, "b": t.destination} for t in donnees.troncons
    ], [n.id for n in donnees.noeuds]


GABARIT = """<!DOCTYPE html>
<html lang="fr">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Réseau de livraison nationale et internationale</title>
<style>
  :root {
    color-scheme: light;
    --page: #f9f9f7; --surface: #fcfcfb;
    --ink-1: #0b0b0b; --ink-2: #52514e; --muted: #898781;
    --hairline: #e1e0d9; --anneau: rgba(11,11,11,0.10);
    --hub: #2a78d6; --agence: #1baf7a; --port: #eb6834; --client: #898781;
    --route: #a9a79f; --congestion: #fab219; --bloque: #d03b3b;
  }
  @media (prefers-color-scheme: dark) {
    :root {
      color-scheme: dark;
      --page: #0d0d0d; --surface: #1a1a19;
      --ink-1: #ffffff; --ink-2: #c3c2b7; --muted: #898781;
      --hairline: #2c2c2a; --anneau: rgba(255,255,255,0.10);
      --hub: #3987e5; --agence: #199e70; --port: #d95926; --client: #898781;
      --route: #56544e; --congestion: #fab219; --bloque: #d03b3b;
    }
  }
  * { box-sizing: border-box; }
  body {
    margin: 0; padding: 22px; background: var(--page); color: var(--ink-1);
    font: 14px/1.5 system-ui, -apple-system, "Segoe UI", sans-serif;
  }
  h1 { font-size: 19px; margin: 0 0 4px; letter-spacing: -0.01em; }
  .sous-titre { color: var(--ink-2); font-size: 13px; margin: 0 0 18px; max-width: 90ch; }
  .rangee { display: flex; gap: 18px; align-items: stretch; flex-wrap: wrap; }
  .bloc {
    background: var(--surface); border: 1px solid var(--anneau);
    border-radius: 10px; padding: 14px 16px;
  }
  .carte { flex: 1 1 380px; min-width: 300px; padding: 12px 14px 6px; }
  .carte.etroite { flex: 0 1 400px; }
  .carte h2, .bloc h2 {
    font-size: 11px; text-transform: uppercase; letter-spacing: 0.07em;
    color: var(--muted); margin: 0 0 2px; font-weight: 600;
  }
  .carte p { margin: 0 0 6px; font-size: 12px; color: var(--ink-2); }
  svg.plan { width: 100%; height: auto; display: block; }
  .rangee.bas { margin-top: 18px; }
  .rangee.bas .bloc { flex: 1 1 260px; }
  .ligne-legende { display: flex; align-items: center; gap: 9px; margin: 6px 0; color: var(--ink-2); font-size: 13px; }
  .ligne-legende svg { width: 22px; height: 14px; flex: none; }
  button {
    display: block; width: 100%; text-align: left; margin: 6px 0; padding: 9px 11px;
    background: transparent; color: var(--ink-1); border: 1px solid var(--hairline);
    border-radius: 7px; font: inherit; font-size: 13px; cursor: pointer;
  }
  button:hover { border-color: var(--muted); }
  button[aria-pressed="true"] { border-color: var(--ink-1); font-weight: 600; }
  .chiffres { display: flex; gap: 22px; margin-top: 12px; }
  .chiffre b { display: block; font-size: 21px; font-weight: 600; line-height: 1.15; }
  .chiffre span { font-size: 11px; color: var(--muted); }
  .alerte { color: var(--bloque); font-weight: 600; }
  #detail { min-height: 168px; font-size: 13px; color: var(--ink-2); }
  #detail .titre { color: var(--ink-1); font-weight: 600; font-size: 14px; margin-bottom: 7px; }
  #detail table { border-collapse: collapse; width: 100%; }
  #detail td { padding: 2px 0; vertical-align: top; }
  #detail td:last-child { text-align: right; color: var(--ink-1); font-variant-numeric: tabular-nums; }
  .note { color: var(--muted); font-size: 11.5px; margin-top: 16px; max-width: 78ch; }
  code { font-size: 11px; }
  .liaison { stroke-linecap: round; }
  .halo { stroke: transparent; stroke-width: 15; fill: none; cursor: pointer; }
  .etiquette { font-size: 11.5px; fill: var(--ink-2); pointer-events: none; }
  .etiquette.majeur { font-size: 12.5px; fill: var(--ink-1); font-weight: 600; }
  .marqueur { stroke: var(--surface); stroke-width: 2; cursor: pointer; }
  .inaccessible { opacity: 0.2; }
</style>
</head>
<body>
<h1>Réseau de livraison nationale et internationale</h1>
<p class="sous-titre">Le graphe du modèle, tracé aux coordonnées GPS réelles. Deux échelles, parce que le projet en a deux : la distribution nationale marocaine et le corridor d'export vers l'Europe. Survolez une liaison pour lire ses données, déclenchez un incident pour voir le réseau se couper.</p>

<div class="rangee">
  <div class="bloc carte">
    <h2>Vue 1 — Distribution nationale</h2>
    <p>Hub de Casablanca, 4 agences régionales, 9 villes clientes.</p>
    <svg class="plan" id="plan-nationale" role="img" aria-label="Carte du réseau national marocain"></svg>
  </div>
  <div class="bloc carte etroite">
    <h2>Vue 2 — Corridor international</h2>
    <p>Sortie par Tanger Med, traversée, puis Espagne et France.</p>
    <svg class="plan" id="plan-corridor" role="img" aria-label="Carte du corridor international Maroc Europe"></svg>
  </div>
</div>

<div class="rangee bas">
  <div class="bloc">
    <h2>Scénarios d'incident</h2>
    <button data-scenario="" aria-pressed="true">Réseau nominal</button>
    <button data-scenario="TMED|ALG" aria-pressed="false">Blocage du ferry Tanger Med – Algésiras</button>
    <button data-scenario="CASA|MRK" aria-pressed="false">Blocage de l'axe Casablanca – Marrakech</button>
    <div class="chiffres">
      <div class="chiffre"><b id="nb-accessibles">–</b><span>nœuds atteignables depuis Casablanca</span></div>
      <div class="chiffre"><b id="nb-coupes">–</b><span>nœuds isolés</span></div>
    </div>
  </div>

  <div class="bloc">
    <h2>Détail</h2>
    <div id="detail">Survolez un nœud ou une liaison.</div>
  </div>

  <div class="bloc">
    <h2>Légende</h2>
    <div class="ligne-legende"><svg viewBox="0 0 22 14"><rect x="4" y="1" width="12" height="12" rx="2" fill="var(--hub)"/></svg> Hub central</div>
    <div class="ligne-legende"><svg viewBox="0 0 22 14"><circle cx="10" cy="7" r="6" fill="var(--agence)"/></svg> Agence régionale</div>
    <div class="ligne-legende"><svg viewBox="0 0 22 14"><path d="M10 0 L18 7 L10 14 L2 7 Z" fill="var(--port)"/></svg> Port — formalités</div>
    <div class="ligne-legende"><svg viewBox="0 0 22 14"><circle cx="10" cy="7" r="4" fill="var(--client)"/></svg> Client</div>
    <div class="ligne-legende"><svg viewBox="0 0 22 14"><line x1="1" y1="7" x2="21" y2="7" stroke="var(--route)" stroke-width="2.5"/></svg> Liaison routière</div>
    <div class="ligne-legende"><svg viewBox="0 0 22 14"><line x1="1" y1="7" x2="21" y2="7" stroke="var(--congestion)" stroke-width="4"/></svg> Axe congestionné</div>
    <div class="ligne-legende"><svg viewBox="0 0 22 14"><line x1="1" y1="7" x2="21" y2="7" stroke="var(--port)" stroke-width="2.5" stroke-dasharray="5 4"/></svg> Traversée maritime</div>
    <div class="ligne-legende"><svg viewBox="0 0 22 14"><line x1="1" y1="7" x2="21" y2="7" stroke="var(--route)" stroke-width="2.5" stroke-dasharray="7 4"/></svg> Passage de frontière</div>
    <div class="ligne-legende"><svg viewBox="0 0 22 14"><line x1="1" y1="7" x2="21" y2="7" stroke="var(--bloque)" stroke-width="3" stroke-dasharray="3 3"/></svg> ✕ Liaison bloquée</div>
  </div>
</div>

<p class="note">Les liaisons sont tracées en segments droits : une arête du graphe est une abstraction dont la longueur réelle (colonne <code>distance_km</code>) est portée par les données, pas par le dessin. Le temps affiché est le temps réel du modèle, congestion et attente de franchissement incluses. L'accessibilité est calculée par parcours en largeur sur le graphe complet depuis le hub de Casablanca.</p>

<script>
const VUES = __VUES__;
const ARETES = __ARETES__;
const TOUS_NOEUDS = __TOUS__;

const FORMES = {
  HUB:    { forme: "carre",   taille: 7,   couleur: "var(--hub)",    majeur: true  },
  AGENCE: { forme: "cercle",  taille: 6.5, couleur: "var(--agence)", majeur: true  },
  PORT:   { forme: "losange", taille: 7.5, couleur: "var(--port)",   majeur: true  },
  CLIENT: { forme: "cercle",  taille: 4.5, couleur: "var(--client)", majeur: false },
};

let bloquees = new Set();
const detail = document.getElementById("detail");
const cle = (a, b) => [a, b].sort().join("|");
const NS = "http://www.w3.org/2000/svg";
const creer = (nom, attrs) => {
  const el = document.createElementNS(NS, nom);
  for (const [k, v] of Object.entries(attrs)) el.setAttribute(k, v);
  return el;
};

/* Parcours en largeur depuis le hub, sur les seules liaisons praticables :
   la version « carte » du graphe non orienté du RouteAgent. */
function accessibles() {
  const voisins = {};
  for (const id of TOUS_NOEUDS) voisins[id] = [];
  for (const a of ARETES) {
    if (bloquees.has(cle(a.a, a.b))) continue;
    voisins[a.a].push(a.b);
    voisins[a.b].push(a.a);
  }
  const vus = new Set(["CASA"]);
  const file = ["CASA"];
  while (file.length) {
    for (const v of voisins[file.shift()]) {
      if (!vus.has(v)) { vus.add(v); file.push(v); }
    }
  }
  return vus;
}

function styleLiaison(l, coupee) {
  if (bloquees.has(cle(l.a, l.b))) return { stroke: "var(--bloque)", width: 3, dash: "3 3" };
  if (coupee) return { stroke: "var(--route)", width: 2, dash: "" };
  if (l.maritime) return { stroke: "var(--port)", width: 2.5, dash: "5 4" };
  if (l.trafic >= 1.2) return { stroke: "var(--congestion)", width: 4, dash: "" };
  if (l.frontiere) return { stroke: "var(--route)", width: 2.5, dash: "7 4" };
  return { stroke: "var(--route)", width: 2.5, dash: "" };
}

function tableau(titre, lignes) {
  return `<div class="titre">${titre}</div><table>` +
    lignes.map(([g, d]) => `<tr><td>${g}</td><td>${d}</td></tr>`).join("") + `</table>`;
}

function dessinerVue(nomVue, vue, vus) {
  const svg = document.getElementById("plan-" + nomVue);
  svg.setAttribute("viewBox", `0 0 ${vue.largeur} ${vue.hauteur}`);
  svg.textContent = "";

  for (const l of vue.liaisons) {
    const estBloquee = bloquees.has(cle(l.a, l.b));
    const coupee = !vus.has(l.a) || !vus.has(l.b);
    const s = styleLiaison(l, coupee);
    const g = creer("g", { class: coupee && !estBloquee ? "inaccessible" : "" });
    g.appendChild(creer("line", {
      class: "liaison", x1: l.x1, y1: l.y1, x2: l.x2, y2: l.y2,
      stroke: s.stroke, "stroke-width": s.width, "stroke-dasharray": s.dash,
    }));
    const halo = creer("line", { class: "halo", x1: l.x1, y1: l.y1, x2: l.x2, y2: l.y2 });
    halo.addEventListener("mouseenter", () => {
      detail.innerHTML = tableau(`${l.na} – ${l.nb}`, [
        ["Distance", l.km + " km"],
        ["Temps de base", l.base + " min"],
        ["Congestion", "× " + l.trafic.toFixed(1)],
        ["Attente frontière", l.attente + " min"],
        ["<b>Temps réel</b>", "<b>" + l.reel + " min</b>"],
        ["Coût fixe", l.cout + " DH"],
        ["Mode", l.maritime ? "maritime (ferry)" : "routier"],
        ["État", estBloquee ? "<span class='alerte'>bloquée</span>" : "praticable"],
      ]);
    });
    g.appendChild(halo);
    svg.appendChild(g);
  }

  /* Croix sur les liaisons bloquées : l'état ne repose jamais sur la couleur seule. */
  for (const l of vue.liaisons) {
    if (!bloquees.has(cle(l.a, l.b))) continue;
    const mx = (l.x1 + l.x2) / 2, my = (l.y1 + l.y2) / 2;
    for (const [dx, dy] of [[-6, -6], [-6, 6]]) {
      svg.appendChild(creer("line", {
        x1: mx + dx, y1: my + dy, x2: mx - dx, y2: my - dy,
        stroke: "var(--bloque)", "stroke-width": 3, "stroke-linecap": "round",
      }));
    }
  }

  for (const n of vue.noeuds) {
    const f = FORMES[n.type];
    const isole = !vus.has(n.id);
    const g = creer("g", { class: isole ? "inaccessible" : "" });
    const t = f.taille;
    let marque;
    if (f.forme === "carre") {
      marque = creer("rect", {
        x: n.x - t, y: n.y - t, width: 2 * t, height: 2 * t, rx: 2,
        fill: f.couleur, class: "marqueur",
      });
    } else if (f.forme === "losange") {
      marque = creer("path", {
        d: `M${n.x} ${n.y - t} L${n.x + t} ${n.y} L${n.x} ${n.y + t} L${n.x - t} ${n.y} Z`,
        fill: f.couleur, class: "marqueur",
      });
    } else {
      marque = creer("circle", { cx: n.x, cy: n.y, r: t, fill: f.couleur, class: "marqueur" });
    }
    marque.addEventListener("mouseenter", () => {
      detail.innerHTML = tableau(n.complet, [
        ["Identifiant", n.id],
        ["Pays", n.pays],
        ["Type", n.type.toLowerCase()],
        ["Traitement sur place", n.traitement + " min"],
        ["Commandes à destination", n.commandes],
        ["État", isole ? "<span class='alerte'>inaccessible</span>" : "atteignable"],
      ]);
    });
    g.appendChild(marque);

    const ecart = t + 7;
    const droite = n.ancrage === "r";
    const texte = creer("text", {
      class: "etiquette" + (f.majeur ? " majeur" : ""),
      x: n.x + (droite ? ecart : -ecart) + n.dx,
      y: n.y + 4 + n.dy,
      "text-anchor": droite ? "start" : "end",
    });
    texte.textContent = n.nom;
    g.appendChild(texte);
    svg.appendChild(g);
  }
}

function dessiner() {
  const vus = accessibles();
  for (const [nom, vue] of Object.entries(VUES)) dessinerVue(nom, vue, vus);
  document.getElementById("nb-accessibles").textContent = vus.size;
  const coupes = document.getElementById("nb-coupes");
  coupes.textContent = TOUS_NOEUDS.length - vus.size;
  coupes.className = vus.size < TOUS_NOEUDS.length ? "alerte" : "";
}

for (const bouton of document.querySelectorAll("button[data-scenario]")) {
  bouton.addEventListener("click", () => {
    for (const autre of document.querySelectorAll("button[data-scenario]"))
      autre.setAttribute("aria-pressed", "false");
    bouton.setAttribute("aria-pressed", "true");
    bloquees = bouton.dataset.scenario
      ? new Set([cle(...bouton.dataset.scenario.split("|"))]) : new Set();
    detail.innerHTML = "Survolez un nœud ou une liaison.";
    dessiner();
  });
}

dessiner();
</script>
</body>
</html>
"""


def main() -> None:
    donnees = charger_tout("data")

    ids_nationale, ids_corridor = vues_par_defaut(donnees)
    vues = {
        "nationale": construire_vue(donnees, "nationale", ids_nationale, 520),
        "corridor": construire_vue(donnees, "corridor", ids_corridor, 560),
    }
    aretes, tous = construire_graphe_complet(donnees)

    page = (
        GABARIT
        .replace("__VUES__", json.dumps(vues, ensure_ascii=False))
        .replace("__ARETES__", json.dumps(aretes, ensure_ascii=False))
        .replace("__TOUS__", json.dumps(tous, ensure_ascii=False))
    )

    sortie = Path("carte_reseau.html")
    sortie.write_text(page, encoding="utf-8")
    print(f"Carte écrite : {sortie} ({len(page) // 1024} Ko)")


if __name__ == "__main__":
    main()