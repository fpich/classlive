# ClassLive Frontend

Interface web React + TypeScript + Tailwind CSS pour la plateforme ClassLive.

## Build

```bash
cd frontend
npm install
npm run build
```

Le build est généré dans `frontend/dist/` avec `base: '/app/'`. Il est servi par le backend FastAPI sur `/app` (voir `frontend_dir` dans `backend/config.yml`). Lancer l'ensemble avec `./start.sh` à la racine du dépôt.

## Structure

```
frontend/
├── index.html
├── package.json
├── vite.config.ts          # build uniquement, base /app/
├── tsconfig.json           # refs app + node
├── tailwind.config.js
├── postcss.config.js
└── src/
    ├── main.tsx            # point d'entrée React
    ├── App.tsx             # routes (BrowserRouter basename=/app)
    ├── index.css           # Tailwind + styles globaux
    ├── types/api.ts        # types TypeScript du contrat OpenAPI
    ├── api/
    │   ├── client.ts       # client HTTP fetch + Bearer token
    │   └── ws.ts           # WebSocket avec reconnexion auto + ping
    ├── store/index.ts      # Zustand : auth formateur, session étudiant, WS live
    ├── components/
    │   ├── UI.tsx          # Button, Input, Card, Badge, Modal, Spinner...
    │   ├── Markdown.tsx    # rendu Markdown (react-markdown + GFM)
    │   ├── ExerciseInput.tsx  # QCM, sondage, texte libre, nuage, échelle, pin...
    │   └── Stats.tsx       # barres de stats agrégées pour le formateur
    └── pages/
        ├── Login.tsx       # connexion formateur
        ├── Home.tsx        # liste groupes/événements, création
        ├── Editor.tsx      # CRUD slides + aperçu Markdown
        ├── LiveSetup.tsx   # configurer et lancer un Live
        ├── LiveControl.tsx # pilotage Live : navigation, stats, élèves, Q&A
        ├── ActiveLives.tsx # retrouver un Live après refresh
        ├── Join.tsx        # /join?code=XXXXXX → inscription étudiant
        └── StudentLive.tsx # interface étudiant (réponses, WS, Q&A, réactions)
```

## Routes

| Chemin | Rôle | Accès |
|---|---|---|
| `/app/` | Accueil formateur (redirige vers login si non connecté) | formateur |
| `/app/login` | Connexion formateur | public |
| `/app/home` | Liste groupes/événements, création, bandeau Live actif | formateur |
| `/app/editor/:group/:event` | Édition des slides | formateur |
| `/app/live/:group/:event` | Configurer un Live | formateur |
| `/app/live-control/:liveId` | Pilotage du Live (code + QR code en panneau latéral) | formateur |
| `/app/lives` | Lives actifs | formateur |
| `/app/join?code=XXXXXX` | Jonction étudiant | public |
| `/app/join/live` | Interface étudiant | étudiant (token) |

## Stack

- **Vite 6** — build rapide, HMR
- **React 18** — composants fonctionnels + hooks
- **TypeScript** — typage strict
- **Tailwind CSS 3** — utilitaires CSS
- **Zustand** — état global léger (persist pour les tokens)
- **react-router-dom 6** — routing SPA
- **react-markdown + remark-gfm** — rendu Markdown des slides
