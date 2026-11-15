# Rapport de validation — ClassLive 0.8.4

**Statut : SUCCÈS** (exécution sur serveur de test isolé dans l'environnement de construction)

## Résultats constatés

- `pytest` : **99 tests réussis**.
- Couverture des lignes Python mesurée séparément avec `pytest-cov` : **89 %**. Le module `__main__` est invoqué par les tests réseau via un processus séparé et n'est pas instrumenté dans cette mesure.
- Inventaire OpenAPI : **41 opérations HTTP**, avec vérification automatique de la liste et refus d'accès anonyme/étudiant sur les routes réservées au formateur.
- WebSocket : **2 routes**, incluant authentification négative, présence, ping/pong, notification de slide et correction.
- Parcours `curl` : **SUCCÈS de bout en bout** sur une instance temporaire, y compris création, modification, navigation, sessions, exports, suppressions et nettoyage.
- Charge fonctionnelle : **30 étudiants simultanés**, 30 connexions WebSocket, 30 inscriptions et réponses concurrentes, 30 notifications de diffusion, déconnexion partielle et présence exacte.
- Persistance : arrêt puis redémarrage d'un vrai processus Uvicorn pendant un Live ; statut, slide, étudiants et réponses récupérés depuis SQLite.
- Non-régression : la correction de la validation YAML renvoie HTTP **422** plutôt qu'une exception non interceptée.
- Script Bash installateur : contrôle syntaxique réussi. Archive vérifiée par `ZipFile.testzip()`.

## Lancer la même validation sur Debian 13

```bash
cd ~/classlive_backend
bash tests/run_suite_complete.sh
```

Tout est effectué sur des répertoires temporaires et des ports de boucle locale alloués dynamiquement. **Aucune requête n'est faite vers le ClassLive de production sur :8080 et aucune donnée du workspace n'est modifiée.** Le journal détaillé sera disponible dans `tests/rapports/derniere_execution.log`.

## Limites de cette validation

La couverture concerne toutes les opérations et fonctionnalités documentées, pas toutes les combinaisons possibles d'entrées. Un test de 30 étudiants ne démontre pas la tenue de charge pendant plusieurs heures ou sur un réseau WLAN instable. Les commandes APT et la configuration réelle de systemd sur une nouvelle machine Debian ne sont pas rejouées par cette suite isolée. Aucun audit de sécurité indépendant n'a été réalisé.
