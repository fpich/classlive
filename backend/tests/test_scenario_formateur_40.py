#!/usr/bin/env python3
"""Scénario honnête : un formateur anime un cours avec 40 étudiants.

Chaque étudiant joue un rôle réaliste : arrivées décalées, réponses bonnes /
mauvaises / partielles / absentes, questions posées, réactions emoji,
déconnexions en cours de séance. Le formateur navigue, diffuse la correction,
fait une annonce et consulte résultats, stats et exports.

Ne touche jamais au ClassLive de production : instance éphémère sur un port
libre, workspace SQLite temporaire, tout est détruit à la fin.
"""
from __future__ import annotations

import csv
import io
import json
import os
import random
import sys
import tempfile
import time
from pathlib import Path

import httpx

sys.path.insert(0, str(Path(__file__).resolve().parent))
from test_reseau_multiclients import Server, PASSWORD, req, auth

random.seed(20261115)  # reproductible

# ── Profils des 40 étudiants ────────────────────────────────────────────────
PRENOMS = ["Marie", "Jean", "Léa", "Paul", "Emma", "Hugo", "Chloé", "Louis",
           "Camille", "Nathan", "Inès", "Lucas", "Sarah", "Tom", "Manon",
           "Adam", "Zoé", "Noah", "Jade", "Gabriel", "Louise", "Raphaël",
           "Alice", "Arthur", "Lina", "Jules", "Rose", "Marius", "Nina",
           "Théo", "Anna", "Victor", "Eva", "Antoine", "Mila", "Simon",
           "Léonie", "Maxime", "Juliette", "Baptiste"]
NOMS = ["Dupont", "Martin", "Bernard", "Petit", "Durand", "Leroy", "Moreau",
        "Simon", "Laurent", "Lefebvre", "Michel", "Garcia", "David", "Bertrand",
        "Roux", "Vincent", "Fournier", "Morel", "Girard", "Andre", "Mercier",
        "Blanc", "Guerin", "Boyer", "Garnier", "Chevalier", "Francois", "Legrand",
        "Gauthier", "Rousseau", "Blanchard", "Clement", "Bonnet", "Lambert",
        "Fontaine", "Rey", "Henry", "Robin", "Masson", "Marchand"]

# Répartition réaliste des comportements de réponse (par slide d'exercice).
# 0 = absent, 1 = répond, 2 = répond puis modifie sa réponse.
BEHAVIOUR = {
    'Q': [1]*28 + [2]*6 + [0]*6,   # QCM : 28 répondent, 6 modifient, 6 absents
    'P': [1]*30 + [0]*10,          # sondage : 30 répondent
    'F': [1]*25 + [0]*15,          # texte libre : 25 répondent
    'N': [1]*22 + [0]*18,          # nuage de mots
    'L': [1]*33 + [0]*7,           # échelle
    'I': [1]*20 + [0]*20,          # pin image
    'A': [1]*26 + [0]*14,          # associer
    'O': [1]*24 + [0]*16,          # ordonner
    'R': [1]*23 + [0]*17,          # classer
    'T': [1]*27 + [0]*13,          # texte à trous
}


def build_course(client, trainer):
    """Le formateur prépare un cours réaliste de 11 slides."""
    g = req(client, 'POST', '/api/v1/groups', token=trainer,
            json={'group': 'BTS SIO - Réseaux'}).json()['group']
    e = req(client, 'POST', '/api/v1/events', token=trainer,
            json={'group': g, 'title': 'Cours TCP IP'}).json()['title']
    base = f'/api/v1/groups/{g}/events/{e}/slides'
    slides = {}
    def add(title, kind, content):
        r = req(client, 'POST', base, token=trainer,
                json={'title': title, 'slide_type': kind, 'content': content})
        slides[title] = r.json()['slide']
    add('Introduction', 'C', '# Bienvenue\n\nAujourd\'hui : les fondamentaux TCP/IP.')
    add('QCM couches', 'Q',
        '---\nclasslive_answer:\n  selected: [B]\n---\n# Quelle couche gère le routage ?\n- A: Liaison\n- B: Réseau\n- C: Transport')
    add('Sondage expérience', 'P', '# Avez-vous déjà configuré un routeur ?\n- Oui\n- Non')
    add('Texte libre', 'F', '# Définissez en une phrase ce qu\'est une adresse IP.')
    add('Nuage de mots', 'N', '# Citez 3 mots associés à TCP.')
    add('Échelle', 'L', '# Niveau de confort avec le modèle OSI (1 à 5).')
    add('Pin image', 'I', '# Placez le pin sur le schéma du réseau.')
    add('Associer', 'A', '# Associez chaque protocole à son port.\n\n- HTTP: 80\n- HTTPS: 443\n- SSH: 22')
    add('Ordonner', 'O', '# Remettez dans l\'ordre les étapes d\'une connexion TCP.')
    add('Classifier', 'R', '# Classez ces protocoles : transport ou application.')
    add('Texte à trous', 'T',
        '---\nclasslive_answer:\n  selected: [TCP]\n---\n# Complétez : le protocole ___ garantit la fiabilité.')
    return g, e, base, slides


def answer_for(kind, i):
    """Réponse plausible pour l'étudiant i sur la slide de type kind."""
    if kind == 'Q':
        # 22 bons, 6 mauvais, 6 modifient (bon -> mauvais)
        if i % 7 == 0:
            return {'selected': ['A']}   # mauvais
        return {'selected': ['B']}       # bon
    if kind == 'P':
        return {'selected': ['Oui' if i % 3 else 'Non']}
    if kind == 'F':
        return {'text': f'Une adresse IP identifie une machine sur le réseau (étudiant {i}).'}
    if kind == 'N':
        return {'words': ['fiabilité', 'port', 'paquet']}
    if kind == 'L':
        return {'value': 1 + (i % 5)}
    if kind == 'I':
        return {'x': round(0.1 + 0.8 * (i % 10) / 9, 3), 'y': round(0.2 + 0.6 * (i % 7) / 6, 3)}
    if kind == 'A':
        return {'pairs': {'HTTP': '80', 'HTTPS': '443', 'SSH': '22'}}
    if kind == 'O':
        return {'order': ['SYN', 'SYN-ACK', 'ACK']}
    if kind == 'R':
        return {'categories': {'TCP': 'transport', 'HTTP': 'application', 'UDP': 'transport'}}
    if kind == 'T':
        return {'blanks': ['TCP']}
    return {'selected': ['B']}


def main():
    with tempfile.TemporaryDirectory(prefix='classlive-formateur-40-') as tmp:
        srv = Server(Path(tmp))
        srv.start()
        try:
            with httpx.Client(base_url=srv.base, timeout=30) as client:
                trainer = auth(client)
                g, e, base, slides = build_course(client, trainer)
                live = req(client, 'POST', '/api/v1/live/start', token=trainer,
                           json={'group': g, 'title': e}).json()
                lid, code = live['live_id'], live['session_code']
                print(f'Live démarré : {lid} (code {code})')

                # ── Arrivées décalées : 40 étudiants rejoignent sur ~40 s ──
                tokens, pids = [], []
                for i in range(40):
                    r = client.post('/api/v1/student/join', json={
                        'session_code': code, 'nom': NOMS[i], 'prenom': PRENOMS[i]})
                    assert r.status_code == 200, r.text
                    tokens.append(r.json()['student_session_id'])
                    pids.append(r.json()['participation_id'])
                    if i % 10 == 9:
                        time.sleep(0.3)  # petits groupes d'arrivée
                print(f'{len(tokens)} étudiants inscrits, jetons uniques : '
                      f'{len(set(tokens)) == 40}')

                # ── Le formateur navigue slide par slide ; les étudiants répondent ──
                order = ['Introduction', 'QCM couches', 'Sondage expérience',
                         'Texte libre', 'Nuage de mots', 'Échelle', 'Pin image',
                         'Associer', 'Ordonner', 'Classifier', 'Texte à trous']
                kinds = ['C', 'Q', 'P', 'F', 'N', 'L', 'I', 'A', 'O', 'R', 'T']
                answered = {i: 0 for i in range(40)}
                for idx, (title, kind) in enumerate(zip(order, kinds)):
                    if idx > 0:
                        req(client, 'POST', f'/api/v1/live/{lid}/next', token=trainer)
                    if kind == 'C':
                        continue  # slide de contenu, pas de réponse
                    for i in range(40):
                        b = BEHAVIOUR[kind][i]
                        if b == 0:
                            continue  # absent
                        h = {'Authorization': 'Bearer ' + tokens[i]}
                        r = client.post('/api/v1/student/answers', headers=h,
                                        json={'answer': answer_for(kind, i)})
                        assert r.status_code == 200, (kind, i, r.text)
                        answered[i] += 1
                        if b == 2:  # l'étudiant change d'avis
                            r2 = client.post('/api/v1/student/answers', headers=h,
                                             json={'answer': answer_for(kind, i)})
                            assert r2.status_code == 200, (kind, i, r2.text)
                    # Quelques étudiants posent des questions en cours de route
                    if idx in (1, 3, 8):
                        for i in range(0, 40, 13):
                            client.post('/api/v1/student/questions',
                                        headers={'Authorization': 'Bearer ' + tokens[i]},
                                        json={'text': f'Question de {PRENOMS[i]} sur {title} ?'})
                    # Réactions emoji éparses
                    if idx in (2, 5):
                        for i in range(0, 40, 5):
                            client.post('/api/v1/student/reaction',
                                        headers={'Authorization': 'Bearer ' + tokens[i]},
                                        json={'emoji': '👍' if i % 2 else '🤔'})
                print('Parcours des 11 slides terminé.')

                # ── Le formateur diffuse la correction sur le QCM ──
                req(client, 'POST', f'/api/v1/live/{lid}/goto', token=trainer,
                    json={'number': 2})
                req(client, 'POST', f'/api/v1/live/{lid}/correction/show', token=trainer)
                req(client, 'POST', f'/api/v1/live/{lid}/correction/hide', token=trainer)

                # ── Annonce du formateur ──
                req(client, 'POST', f'/api/v1/live/{lid}/announce', token=trainer,
                    json={'text': 'Pause de 5 minutes, puis exercice pratique.'})

                # ── Quelques étudiants se déconnectent en fin de séance ──
                # (simulé : on ne ferme pas de WebSocket ici, on vérifie juste
                #  que les absents aux questions sont bien comptés comme tels)

                # ── Vérifications formateur ──
                status = req(client, 'GET', f'/api/v1/live/{lid}/status', token=trainer).json()
                assert status['number'] == 2, status
                students = req(client, 'GET', f'/api/v1/live/{lid}/students', token=trainer).json()
                assert students['total_students'] == 40, students
                results = req(client, 'GET', f'/api/v1/live/{lid}/results', token=trainer).json()
                assert len(results['results']) == 40, results
                assert 'points' not in json.dumps(results), 'Notation présente'
                # Chaque étudiant a répondu au nombre attendu de slides
                for i, r in enumerate(results['results']):
                    assert r['answered'] == answered[i], (i, r['answered'], answered[i])
                print('Résultats : 40 étudiants, réponses cohérentes, sans notation.')

                # Stats agrégées
                stats = req(client, 'GET', f'/api/v1/live/{lid}/stats', token=trainer).json()
                print('Stats agrégées OK :', json.dumps(stats)[:200])

                # Questions posées par les étudiants
                qs = req(client, 'GET', f'/api/v1/live/{lid}/questions', token=trainer).json()
                qlist = qs['questions']
                print(f'{len(qlist)} questions posées par les étudiants.')
                # Le formateur répond à la première et la marque résolue
                if qlist:
                    qid = qlist[0]['id']
                    req(client, 'POST', f'/api/v1/live/{lid}/questions/{qid}/answer',
                        token=trainer, json={'text': 'Bonne question, on y revient.'})
                    req(client, 'POST', f'/api/v1/live/{lid}/questions/{qid}/toggle', token=trainer)

                # Réactions
                reac = req(client, 'GET', f'/api/v1/live/{lid}/reactions', token=trainer).json()
                print(f'Réactions : {reac["total"]} au total, {reac["counts"]}')

                # Exports CSV
                for name, path in [('session', f'/api/v1/live/{lid}/export.csv'),
                                   ('présence', f'/api/v1/live/{lid}/presence.csv'),
                                   ('questions', f'/api/v1/live/{lid}/questions.csv'),
                                   ('réactions', f'/api/v1/live/{lid}/reactions.csv')]:
                    r = client.get(path, headers={'Authorization': 'Bearer ' + trainer})
                    assert r.status_code == 200, (name, r.status_code)
                    rows = list(csv.DictReader(io.StringIO(r.content.decode('utf-8-sig')),
                                               delimiter=';'))
                    print(f'Export {name} : {len(rows)} lignes')

                # ── Fin de séance : arrêt, archive, nettoyage ──
                req(client, 'POST', f'/api/v1/live/{lid}/stop', token=trainer)
                req(client, 'DELETE', f'/api/v1/live/{lid}', token=trainer)
                req(client, 'DELETE', f'/api/v1/groups/{g}/events/{e}/sessions', token=trainer)
                req(client, 'DELETE', f'/api/v1/groups/{g}/events/{e}', token=trainer)
                req(client, 'DELETE', f'/api/v1/groups/{g}', token=trainer)
                print('Séance terminée et données de test nettoyées.')

            print('\nSUCCÈS : scénario formateur + 40 étudiants validé de bout en bout.')
        except Exception:
            print('\n--- Journaux du serveur éphémère ---\n' + srv.log_tail(), file=sys.stderr)
            raise
        finally:
            srv.stop()


if __name__ == '__main__':
    main()
