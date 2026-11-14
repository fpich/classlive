#!/usr/bin/env bash
# Tests fonctionnels de ClassLive 0.9.1 sur HTTP (sans frontend).
# Le script ne touche qu'aux groupes et événements de test qu'il crée.
set -Eeuo pipefail
BASE="${CLASSLIVE_URL:-http://127.0.0.1:8080}"
BASE="${BASE%/}"
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
if [[ ! -f "$SCRIPT_DIR/ws_live_smoke.py" && -f "$SCRIPT_DIR/tests/ws_live_smoke.py" ]]; then
  SCRIPT_DIR="$SCRIPT_DIR/tests"
fi
WS_PYTHON="${CLASSLIVE_PYTHON:-/opt/classlive/.venv/bin/python}"
if [[ ! -x "$WS_PYTHON" ]]; then WS_PYTHON=python3; fi

WORK="$(mktemp -d)"
trap 'rm -rf "$WORK"' EXIT
REPLY_FILE="$WORK/response"
STEP=0

info(){ printf '\n\033[1;34m[%02d] %s\033[0m\n' "$((++STEP))" "$*"; }
fail(){ printf '\nÉCHEC : %s\n' "$*" >&2; if [[ -s "$REPLY_FILE" ]]; then cat "$REPLY_FILE" >&2; echo >&2; fi; exit 1; }
json(){ python3 -c 'import json,sys; obj=json.load(sys.stdin); print(obj[sys.argv[1]])' "$1"; }
json_str(){ python3 -c 'import json,sys; print(json.dumps(sys.argv[1],ensure_ascii=False))' "$1"; }
number(){ python3 -c 'import sys,re; print(int(re.match(r"[GES](\d+)_",sys.argv[1]).group(1)))' "$1"; }
payload_slide(){ python3 -c 'import json,sys; print(json.dumps({"title":sys.argv[1],"slide_type":sys.argv[2],"content":sys.argv[3]},ensure_ascii=False))' "$1" "$2" "$3"; }
result(){ cat "$REPLY_FILE"; echo; }
# Usage req EXPECT METHOD PATH {trainer|student|public} [payload] ; optionally e.g. 200,409
req(){
 local expected="$1" method="$2" path="$3" role="$4" payload="${5-}" code
 local -a opts=(--silent --show-error --max-time 20 --output "$REPLY_FILE" --write-out '%{http_code}' --request "$method")
 [[ "$role" != "trainer" ]] || opts+=(-H "Authorization: Bearer $TRAINER_TOKEN")
 [[ "$role" != "student" ]] || opts+=(-H "Authorization: Bearer $STUDENT_TOKEN")
 if [[ $# -ge 5 ]]; then opts+=(-H 'Content-Type: application/json' --data "$payload"); fi
 code="$(curl "${opts[@]}" "$BASE$path")" || fail "Impossible de joindre $BASE$path"
 [[ "$code" == "$expected" ]] || fail "$method $path : HTTP $code au lieu de $expected"
 printf '%s %-6s %s\n' "$code" "$method" "$path"
}

info 'Disponibilité, OpenAPI et documentation Markdown'
req 200 GET /health public; result
python3 -c 'import json,sys; o=json.load(open(sys.argv[1])); assert o["status"] == "ok" and o["version"] == "0.9.1",o' "$REPLY_FILE" || fail 'Version ClassLive inattendue (0.9.1 requise)' 
req 200 GET /openapi.json public
python3 -m json.tool "$REPLY_FILE" >/dev/null || fail 'OpenAPI invalide'
req 200 GET /api/v1/help public
head -n 2 "$REPLY_FILE"
req 401 GET /api/v1/groups public
req 401 POST /api/v1/live/start public '{"group":"interdit","title":"interdit"}' 

if [[ -z "${CLASSLIVE_PASSWORD:-}" ]]; then
  printf '\nMot de passe du formateur (voir /etc/classlive/classlive.env) : ' >&2
  read -r -s CLASSLIVE_PASSWORD
  printf '\n' >&2
fi
info 'Authentification formateur / rejet du mauvais mot de passe'
req 401 POST /api/v1/auth/login public '{"username":"formateur","password":"FAUX_MOT_DE_PASSE"}'
# En cas de saisie interactive, variable shell non exportée : la passer via stdin pour éviter les arguments de curl visibles.
LOGIN_DATA="$(printf '%s' "$CLASSLIVE_PASSWORD" | python3 -c 'import json,sys;print(json.dumps({"username":"formateur","password":sys.stdin.read()}))')"
req 200 POST /api/v1/auth/login public "$LOGIN_DATA"
TRAINER_TOKEN="$(json access_token < "$REPLY_FILE")"
unset CLASSLIVE_PASSWORD LOGIN_DATA
req 401 GET /api/v1/groups public

PREFIX="Test_API_$(date +%Y%m%d_%H%M%S)_$$"
info "Création des groupes et normalisation des noms ($PREFIX)"
req 200 POST /api/v1/groups trainer "{\"group\":\"$PREFIX Formation d'été\"}"
G1="$(json group < "$REPLY_FILE")"; echo "Groupe : $G1"
req 200 POST /api/v1/groups trainer "{\"group\":\"$PREFIX Autre groupe\"}"
G2="$(json group < "$REPLY_FILE")"; echo "Groupe secondaire : $G2"
req 200 GET /api/v1/groups trainer; result
req 200 POST /api/v1/groups trainer "{\"group\":\"$PREFIX Formation d'été\"}"
python3 -c 'import json,sys; assert json.load(open(sys.argv[1]))["created"] is False' "$REPLY_FILE" || fail 'Idempotence création groupe'

info 'Unicité Gxxx et renommage groupe (nom + numéro)'
N1="$(number "$G1")"
req 409 PATCH "/api/v1/groups/$G2" trainer "{\"new_number\":$N1}"
req 200 PATCH "/api/v1/groups/$G2" trainer "{\"new_name\":\"${PREFIX}_Groupe_de_test_secondaire\"}"
G2="$(json new_name < "$REPLY_FILE")"

info 'Création événements et renommages E###'
req 200 POST /api/v1/events trainer "{\"group\":\"$G1\",\"title\":\"$PREFIX Introduction d'été\"}"
E1="$(json title < "$REPLY_FILE")"; echo "Événement : $E1"
req 200 POST /api/v1/events trainer "{\"group\":\"$G1\",\"title\":\"$PREFIX Evenement secondaire\"}"
E2="$(json title < "$REPLY_FILE")"
req 200 GET "/api/v1/groups/$G1/events" trainer; result
N_E1="$(number "$E1")"
req 409 PATCH "/api/v1/groups/$G1/events/$E2" trainer "{\"new_number\":$N_E1}"
req 200 PATCH "/api/v1/groups/$G1/events/$E2" trainer '{"new_name":"Autre_evenement"}'
E2="$(json new_name < "$REPLY_FILE")"
req 200 PATCH "/api/v1/groups/$G1/events/$E1" trainer '{"new_name":"Cours_de_validation_API"}'
E1="$(json new_name < "$REPLY_FILE")"

SLIDES="/api/v1/groups/$G1/events/$E1/slides"
info 'Création des six types de slides C, Q, A, O, R, T'
req 200 POST "$SLIDES" trainer "$(payload_slide 'Bienvenue' C '# Introduction ClassLive')"
S1="$(json slide < "$REPLY_FILE")"
QCONTENT=$'---\nclasslive_answer:\n  selected: [B]\n---\n# Quelle est la capitale de la France ?\n\n- A: Lyon\n- B: Paris\n- C: Nice'
req 200 POST "$SLIDES" trainer "$(payload_slide 'Question capitale' Q "$QCONTENT")"
S2="$(json slide < "$REPLY_FILE")"
req 200 POST "$SLIDES" trainer "$(payload_slide 'Associer' A $'# Associer\n\nAssocier A avec 1.')"
S3="$(json slide < "$REPLY_FILE")"
req 200 POST "$SLIDES" trainer "$(payload_slide 'Ordonner' O '# Mettre dans l ordre')"
S4="$(json slide < "$REPLY_FILE")"
req 200 POST "$SLIDES" trainer "$(payload_slide 'Classifier' R '# Classer les éléments')"
S5="$(json slide < "$REPLY_FILE")"
req 200 POST "$SLIDES" trainer "$(payload_slide 'Texte à trous' T '# Compléter le texte')"
S6="$(json slide < "$REPLY_FILE")"
req 200 GET "$SLIDES" trainer; result
python3 - "$REPLY_FILE" <<'PY_CHECK'
import json,sys
names=json.load(open(sys.argv[1]))['slides']
assert len(names)==6 and {x.split('_')[1] for x in names} == set('CQ AORT'.replace(' ','')), names
PY_CHECK
req 200 GET "$SLIDES/$S2" trainer
python3 -c 'import json,sys; assert "classlive_answer" in json.load(open(sys.argv[1]))["content"]' "$REPLY_FILE" || fail 'Corrigé absent du fichier Markdown administrateur'

info 'Conflit Sxxx, mise à jour du Markdown et renommage slide'
req 409 POST "$SLIDES" trainer "$(python3 -c 'import json;print(json.dumps({"title":"Numero doublon","slide_type":"Q","number":2,"content":"# Erreur"}))')"
req 409 PATCH "$SLIDES/$S6" trainer '{"new_number":2}'
req 200 PUT "$SLIDES/$S1/content" trainer '{"content":"# Introduction ClassLive mise a jour"}'
req 200 GET "$SLIDES/$S1" trainer
python3 -c 'import json,sys; assert "mise a jour" in json.load(open(sys.argv[1]))["content"]' "$REPLY_FILE" || fail 'Édition du contenu'
req 200 PATCH "$SLIDES/$S6" trainer '{"new_number":8,"new_name":"Exercice_de_texte"}'
S6="$(json new_name < "$REPLY_FILE")"
req 200 GET "$SLIDES" trainer; result

info 'Lecteur indépendant /player (select, next, previous, current, close)'
req 200 POST /api/v1/player/select trainer "{\"group\":\"$G1\",\"title\":\"$E1\"}"
PLAYER="$(json session_id < "$REPLY_FILE")"
req 200 POST "/api/v1/player/$PLAYER/next" trainer
req 200 POST "/api/v1/player/$PLAYER/previous" trainer
python3 -c 'import json,sys;assert json.load(open(sys.argv[1]))["slide"].startswith("S001_")' "$REPLY_FILE" || fail 'Navigation précédent incorrecte'
req 200 GET "/api/v1/player/$PLAYER" trainer
req 200 DELETE "/api/v1/player/$PLAYER" trainer
req 404 GET "/api/v1/player/$PLAYER" trainer

info 'Démarrer Live ; interdire un second Live simultané'
req 200 POST /api/v1/live/start trainer "{\"group\":\"$G1\",\"title\":\"$E1\"}"
LIVE="$(json live_id < "$REPLY_FILE")"; CODE="$(json session_code < "$REPLY_FILE")"
echo "Live de test créé : $LIVE"
req 409 POST /api/v1/live/start trainer "{\"group\":\"$G1\",\"title\":\"$E1\"}"
req 200 GET "/api/v1/live/$LIVE/status" trainer
python3 -c 'import json,sys; o=json.load(open(sys.argv[1])); assert o["number"] == 1 and o["total"] == 6, o' "$REPLY_FILE" || fail 'État initial Live incorrect'
req 200 POST "/api/v1/live/$LIVE/previous" trainer
python3 -c 'import json,sys; assert json.load(open(sys.argv[1]))["number"]==1' "$REPLY_FILE" || fail 'Dépassement avant première slide'
req 404 POST "/api/v1/live/$LIVE/goto" trainer '{"number":999}' 
req 200 GET "/api/v1/groups/$G1/events/$E1/sessions" trainer
req 409 PATCH "/api/v1/groups/$G1/events/$E1" trainer '{"new_name":"Interdit_pendant_archivage"}'

info 'Inscription étudiant autonome et reconnexion'
req 404 POST /api/v1/student/join public '{"session_code":"000000","nom":"Dupont","prenom":"Marie"}'
req 422 POST /api/v1/student/join public "{\"session_code\":\"$CODE\",\"nom\":\" \",\"prenom\":\"Marie\"}"
req 200 POST /api/v1/student/join public "{\"session_code\":\"$CODE\",\"nom\":\"Dupont\",\"prenom\":\"Marie\"}"
STUDENT_TOKEN="$(json student_session_id < "$REPLY_FILE")"
echo 'Jeton étudiant récupéré (valeur masquée).'
req 200 POST /api/v1/student/resume student
req 200 GET /api/v1/student/current student
req 401 GET /api/v1/groups student
req 401 GET "/api/v1/live/$LIVE/students" student
req 200 GET "/api/v1/live/$LIVE/students" trainer; result
python3 - "$REPLY_FILE" <<'PY_CHECK'
import json,sys
r=json.load(open(sys.argv[1]))
assert r['total_students']==1 and r['students'][0]['nom']=='Dupont', r
assert 'student_session_id' not in json.dumps(r), 'Fuite du jeton privé étudiant'
PY_CHECK

info 'WebSocket réel (étudiant, formateur, ping, synchronisation et déconnexion)'
if [[ "${CLASSLIVE_SKIP_WEBSOCKET:-0}" != 1 ]]; then
  [[ -f "$SCRIPT_DIR/ws_live_smoke.py" ]] || fail 'Fichier tests/ws_live_smoke.py manquant'
  CLASSLIVE_URL="$BASE" CLASSLIVE_TRAINER_TOKEN="$TRAINER_TOKEN" \
  CLASSLIVE_STUDENT_TOKEN="$STUDENT_TOKEN" CLASSLIVE_LIVE_ID="$LIVE" \
  "$WS_PYTHON" "$SCRIPT_DIR/ws_live_smoke.py" || fail 'Test WebSocket réel non validé'
else
  echo 'WebSocket non exécuté : CLASSLIVE_SKIP_WEBSOCKET=1 (couverture partielle)'
fi

info 'Live : refus de réponse sur contenu C ; navigation et corrigé masqué'
req 409 POST /api/v1/student/answers student '{"answer":{"selected":["B"]}}'
req 409 POST "/api/v1/live/$LIVE/correction/show" trainer
req 200 POST "/api/v1/live/$LIVE/next" trainer
req 200 GET /api/v1/student/current student
python3 -c 'import json,sys; o=json.load(open(sys.argv[1])); assert "classlive_answer" not in json.dumps(o) and "correction" not in o' "$REPLY_FILE" || fail 'Fuite du corrigé avant affichage'
# Le snapshot Live doit rester figé même si le formateur change le Markdown source.
req 200 PUT "$SLIDES/$S2/content" trainer '{"content":"# Changement interdit pendant le Live"}'
# Un étudiant ne doit pas pouvoir accéder au Markdown et au corrigé brut.
req 401 GET "$SLIDES/$S2" student
req 200 GET /api/v1/student/current student
python3 -c 'import json,sys; o=json.load(open(sys.argv[1])); assert "capitale" in o["content"] and "Changement interdit" not in o["content"],o' "$REPLY_FILE" || fail 'Le snapshot Live a changé après modification de la source' 
req 200 POST /api/v1/student/answers student '{"answer":{"selected":["A"]}}'
req 200 POST /api/v1/student/answers student '{"answer":{"selected":["B"]}}'
req 200 POST "/api/v1/live/$LIVE/correction/show" trainer
req 200 GET /api/v1/student/current student
python3 -c 'import json,sys; o=json.load(open(sys.argv[1])); assert o["correction"]=={"selected":["B"]}' "$REPLY_FILE" || fail 'Correction non visible après show'
req 409 POST /api/v1/student/answers student '{"answer":{"selected":["B"]}}'
req 200 POST "/api/v1/live/$LIVE/correction/hide" trainer
req 200 GET /api/v1/student/current student
python3 -c 'import json,sys; assert "correction" not in json.load(open(sys.argv[1]))' "$REPLY_FILE" || fail 'Correction visible après hide'
req 200 POST "/api/v1/live/$LIVE/previous" trainer
req 200 POST "/api/v1/live/$LIVE/goto" trainer '{"number":3}'
req 200 POST /api/v1/student/answers student '{"answer":{"pairs":{"A":"1"}}}'
req 200 POST "/api/v1/live/$LIVE/goto" trainer '{"number":4}'
req 200 POST /api/v1/student/answers student '{"answer":{"order":["B","A","C"]}}'
req 200 POST "/api/v1/live/$LIVE/goto" trainer '{"number":5}'
req 200 POST /api/v1/student/answers student '{"answer":{"categories":{"chat":"animaux"}}}'
req 200 POST "/api/v1/live/$LIVE/goto" trainer '{"number":8}'
req 200 POST /api/v1/student/answers student '{"answer":{"blanks":["Paris"]}}'

info 'Résultats sans points, CSV par session et événement, statut étudiant'
req 200 GET "/api/v1/live/$LIVE/results" trainer
python3 - "$REPLY_FILE" <<'PY_CHECK'
import json,sys
result=json.load(open(sys.argv[1]))['results']
assert len(result)==1 and result[0]['answered']==5,result
answers={x['slide']:x['answer'] for x in result[0]['answers']}
assert any(k.startswith('S002_') and v=={'selected':['B']} for k,v in answers.items()),answers
PY_CHECK
python3 -c 'import json,sys; o=json.load(open(sys.argv[1])); assert "points" not in json.dumps(o)' "$REPLY_FILE" || fail 'Notation présente par erreur'
req 200 GET "/api/v1/live/$LIVE/students" trainer; result
req 200 GET "/api/v1/live/$LIVE/export.csv" trainer
cp "$REPLY_FILE" ./classlive_test_session.csv
python3 -c 'import csv,sys;rows=list(csv.DictReader(open(sys.argv[1],encoding="utf-8-sig"),delimiter=";"));assert len(rows)>=5,rows;assert "points" not in rows[0]' ./classlive_test_session.csv || fail 'Export CSV session incorrect'
req 200 GET "/api/v1/groups/$G1/events/$E1/export.csv" trainer
cp "$REPLY_FILE" ./classlive_test_evenement.csv
python3 -c 'import csv,sys; rows=list(csv.DictReader(open(sys.argv[1],encoding="utf-8-sig"),delimiter=";")); assert len(rows)==5,rows' ./classlive_test_evenement.csv || fail 'Export CSV événement incorrect' 

info 'Arrêt, archive session, rejet de reconnexion, suppression session'
req 409 DELETE "/api/v1/live/$LIVE" trainer
req 200 POST "/api/v1/live/$LIVE/stop" trainer
req 401 POST /api/v1/student/resume student
req 200 GET "/api/v1/groups/$G1/events/$E1/sessions" trainer; result
req 200 GET "/api/v1/live/$LIVE/results" trainer
req 200 DELETE "/api/v1/live/$LIVE" trainer
req 404 GET "/api/v1/live/$LIVE/results" trainer

info 'Second Live, arrêt, réinitialisation globale de l’événement'
req 200 POST /api/v1/live/start trainer "{\"group\":\"$G1\",\"title\":\"$E1\"}"
LIVE2="$(json live_id < "$REPLY_FILE")"
req 409 DELETE "/api/v1/groups/$G1/events/$E1/sessions" trainer
req 200 POST "/api/v1/live/$LIVE2/stop" trainer
req 200 GET "/api/v1/groups/$G1/events/$E1/sessions" trainer
python3 -c 'import json,sys;assert len(json.load(open(sys.argv[1]))["sessions"])==1' "$REPLY_FILE" || fail 'Historique des sessions incorrect' 
req 200 DELETE "/api/v1/groups/$G1/events/$E1/sessions" trainer
req 200 GET "/api/v1/groups/$G1/events/$E1/sessions" trainer
python3 -c 'import json,sys;assert not json.load(open(sys.argv[1]))["sessions"]' "$REPLY_FILE" || fail 'Sessions non réinitialisées'

info 'Suppression de slide, d’événements et de groupes de TEST UNIQUEMENT'
req 200 DELETE "$SLIDES/$S6" trainer
req 200 DELETE "/api/v1/groups/$G1/events/$E2" trainer
req 200 DELETE "/api/v1/groups/$G1/events/$E1" trainer
req 200 DELETE "/api/v1/groups/$G2" trainer
req 200 DELETE "/api/v1/groups/$G1" trainer
req 200 GET /api/v1/groups trainer
python3 - "$REPLY_FILE" "$PREFIX" <<'PY_CHECK'
import json,sys
items=json.load(open(sys.argv[1]))['groups']
assert not any(sys.argv[2] in group for group in items),items
PY_CHECK

printf '\n\033[1;32mSUCCÈS : tous les tests REST ont réussi.\033[0m\n'
printf 'Exports sauvegardés : ./classlive_test_session.csv et ./classlive_test_evenement.csv\n'
printf 'WebSocket testé via Python (websockets), en complément des requêtes curl.\n'
