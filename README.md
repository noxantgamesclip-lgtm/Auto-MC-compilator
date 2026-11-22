# AutoCompilateur

Petit logiciel Windows : tu glisses un **ZIP** de projet (plugin Paper/Spigot ou mod Fabric/Forge/NeoForge, en Gradle ou Maven) et il te rend le **.jar**.

## Obtenir le .exe (sans installer Python)
1. Crée un dépôt GitHub **privé** (ex. `AutoCompilateur`) et envoie-y le contenu de ce dossier (`app.py`, `core.py`, `requirements.txt`, `README.md` et `.github/workflows/build-exe.yml`).
2. Onglet **Actions** : la compilation démarre seule (2 à 5 minutes).
3. Télécharge l'artifact **AutoCompilateur-exe** : le `.exe` est dedans.
4. Chrome et Windows SmartScreen peuvent avertir (« éditeur inconnu » : le programme n'est pas signé). Clique sur **Conserver**, puis **Informations complémentaires > Exécuter quand même**.

## Utilisation
Lance `AutoCompilateur.exe`, glisse ton ZIP (ou **Choisir un ZIP…**), attends. Le `.jar` apparaît dans un dossier `NomDuZip-jar` à côté du ZIP, qui s'ouvre tout seul.
Le menu **Java** reste sur *Auto* sauf si la compilation échoue pour une raison de version.

## Ce qu'il fait
Décompresse (en refusant les chemins suspects) → trouve le projet → détecte la version de Java → télécharge Java (Adoptium), Gradle ou Maven si besoin → compile avec `build` / `package` → copie les `.jar` utiles (sans `-sources`, `-javadoc`, `-dev`).

## Limites
- **Internet requis**, surtout au premier lancement (Java + dépendances : plusieurs centaines de Mo ; les mods Forge/NeoForge/Fabric peuvent prendre de longues minutes).
- Il **compile, il ne corrige pas** : une erreur de code est affichée, pas réparée.
- **Sécurité** : un script de build peut exécuter du code. Ne compile que des ZIP de confiance.
- Les très vieux mods (Forge 1.12 et avant) demandent parfois des réglages particuliers.
- **Testé** : la logique de détection (projets factices, ZIP piégé, sélection des .jar). **Non testé** : l'interface, le `.exe` et une vraie compilation sous Windows.
