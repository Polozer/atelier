# Prompt pour Claude — coques du train Belmonte dans Blender

Construis dans Blender les deux voitures d'un train extrêmement luxueux reliant Belmonte, la ville toscane de Haras Valley, à la ville de Yorimichi. Hidamari est le nom provisoire de la destination. Mon frère travaille actuellement sur l'intégration de la carte de Belmonte : ton travail doit rester indépendant de cette intégration.

Travaille à partir du fork personnel `Polozer/atelier`, dont le checkout canonique est `$HOME/AI/atelier-main`. `fontanierh/atelier` reste l'upstream de mon frère. Lis les `AGENTS.md` applicables, les conventions d'Atelier et les guides existants avant de commencer. Si d'autres agents modifient ce checkout, utilise un worktree distinct selon les règles du dépôt, sans réinitialiser le travail existant. Respecte les règles de coordination, de verrouillage et de mémoire pour Blender et Unreal.

## Décisions déjà prises

- Deux voitures seulement : restaurant et première classe à cabines privées assises. Aucun lit ; locomotive, rails, gare et gameplay de transport restent hors de cette étape.
- Direction Orient Express : luxe européen Belle Époque avec Art déco discret, carrosserie bleu nuit, bande ivoire, filets or champagne, laiton, toit charcoal arrondi, blason original soleil et rameau d'olivier.
- Restaurant accepté : boiseries en noyer et marqueterie végétale, velours bordeaux, tables avec linge ivoire, circulation centrale, bar et cuisine à une extrémité.
- Première classe acceptée : compartiments fermés donnant sur un couloir latéral. Deux canapés deux places en velours émeraude se font face dans chaque cabine ; une petite table est près de la fenêtre ; porte coulissante vitrée en noyer et laiton. L'ancien salon ouvert est abandonné.
- De l'extérieur, les fenêtres doivent laisser voir le véritable intérieur vide. Les vitrages sont des objets et matériaux séparés ; les ouvertures traversent réellement la coque. Un intérieur peint dans une texture de vitre ne convient pas.
- Nous préparons séparément les meubles et accessoires dans Tripo Studio avec mes crédits Studio. Tu construis la coque, l'architecture et les points d'accueil du mobilier. Aucun appel Tripo API n'est demandé.

## Références à consulter

Dans le checkout canonique :

- `games/yorimichi/docs/BELMONTE_TRAIN_PROMPT.md` : historique et direction actuelle.
- `build/yorimichi/train-concepts/r02/README.md` et `manifest.json` : index des douze vues.
- `restaurant-furnished-front.png`, `restaurant-furnished-reverse.png` : restaurant avec mobilier.
- `restaurant-empty-front.png`, `restaurant-empty-reverse.png` : architecture seule.
- `first-class-furnished-front.png` : cabine vue droit vers la fenêtre.
- `first-class-furnished-corridor.png` : depuis la cabine vers le couloir.
- `first-class-empty-front.png`, `first-class-empty-corridor.png` : mêmes directions sans mobilier.
- `restaurant-exterior-{profile,three-quarter}.png` et `first-class-exterior-{profile,three-quarter}.png` : extérieurs avec l'intérieur vide visible.
- `build/yorimichi/train-concepts/train-reference-pack-r02.zip` : export portable des références. Les images du build sont locales et ignorées par Git ; si tu travailles sur un autre ordinateur, récupère ce pack avant de dessiner.
- `games/yorimichi/assets/vehicles/belmonte-train/planning/furniture-dimensions.json` : contrat de dimensions provisoire partagé avec les assets Tripo.
- `games/yorimichi/docs/TREEHOUSE_PLAN.md`, section « Script or Tripo » : architecture dimensionnée par script, objets individuels via Tripo.
- `platform/conventions/units.md` et `naming.md` : unités, axes et identifiants.

Les images sont des inspirations, pas un relevé géométrique. Certaines répétitions de fenêtres et proportions peuvent varier entre images générées : produis un seul plan cohérent et explique les choix de raccord entre l'extérieur et l'intérieur.

## Plan et dimensions

Commence par un plan coté et un blockout paramétrique, puis modèle les deux coques vides. Base de travail : 24 m sur attelages, 3,10 m de largeur extérieure, 4,30 m de haut au-dessus du rail, 2,30 m de hauteur intérieure libre. Ces valeurs restent des cibles de conception à valider.

Le contrat propose 75 mm de paroi de chaque côté, soit 2,95 m intérieurs. Première classe : cabine de 2,00 m de large, cloison de 50 mm, couloir de 0,90 m ; la somme est 2,95 m. La cible de 2,05 m du premier concept est donc ajustée à 2,00 m dans ce plan de départ. Prévois quatre cabines d'environ 3 m de longueur chacune ; répartis correctement les espaces restants entre vestibules, bagages, sanitaires et service, sans étirer artificiellement les cabines.

Restaurant : quatre travées de repas comme point de départ, deux tables par travée, deux convives face à face par table, soit seize places. Conserve un passage central d'au moins 0,95 m. Réconcilie les six grandes fenêtres du concept extérieur avec les zones repas, bar et service dans le plan final. Les quantités sont provisoires jusqu'à ce contrôle.

Lis les dimensions des six objets depuis le JSON pour placer des volumes temporaires : banquette restaurant 0,90 × 0,65 × 1,15 m ; table restaurant 0,80 × 0,65 × 0,75 m ; canapé cabine 1,85 × 0,78 × 1,10 m ; petite table 0,65 × 0,40 × 0,62 m ; lampe de table 0,24 × 0,24 × 0,40 m ; applique 0,18 × 0,22 × 0,40 m. Hauteur d'assise 0,46 m. Prévois l'encombrement du linge de table, les genoux, les accès et l'ouverture des portes. Vérifie les dimensions du personnage déclaré dans Yorimichi et ses besoins de caméra ; à défaut, utilise un gabarit humain de 1,75 m clairement identifié comme provisoire.

Si le blockout exige de changer une cible, documente le problème, ajuste le contrat commun et indique les objets affectés. Les meshes Tripo seront ensuite mis aux dimensions et contrôlés ; les dimensions d'une image ne sont pas celles d'un mesh.

## Architecture à produire

Modèle une enveloppe commune réutilisée : châssis, sol, côtés, toit amovible pour inspection, deux bogies, attelages, gangways et vestibules. Les deux plans intérieurs sont distincts. Sépare vitrage, portes, cloisons, matériaux et éléments qui doivent s'animer ou se remplacer. Structure de première classe : parois des cabines et du couloir latéral, portes coulissantes, encadrements et vrais passages. Structure du restaurant : salon continu, vestibules, séparation de la cuisine et réservations pour le bar.

Conserve les boiseries, marqueteries, panneaux de plafond et moquettes des références. Utilise des motifs paramétriques, textures de détail ou trim sheets pour les ornements fins, plutôt que multiplier les petits éléments de géométrie. Les coques finales doivent être vides : meubles, lampes, rideaux, racks et objets décoratifs restent séparés. Tu peux créer des volumes de réservation et des repères pour ces objets, pas des meubles détaillés en remplacement des assets Studio.

Auteur des modèles en mètres, Z vers le haut. Respecte les axes d'Atelier et sa conversion officielle vers Unreal ; évite une seconde rotation ou inversion improvisée. Objets de mobilier : largeur locale X, profondeur Y, face vers -Y, hauteur Z. Origines au centre de l'empreinte au sol ; lampes de table au centre de contact de leur base ; appliques au point de fixation mural. Fournis des points de placement nommés, des marqueurs d'assise et un JSON de placements en mètres.

## Livraison attendue

1. Plan coté et contrat de dimensions mis à jour, avec hypothèses de gauge, vestibules et attelages clairement séparées des dimensions validées.
2. Sources reproductibles sous le jeu, par exemple dans `games/yorimichi/world/train/`, et bibliothèque source sous `games/yorimichi/assets/vehicles/belmonte-train/`. Aucun fichier du jeu dans la plateforme générique. Les outputs générés et rendus restent sous `build/yorimichi/`.
3. Fichiers `.blend` propres des deux coques, collections nommées, matériaux partagés et toit démontable pour examiner les espaces.
4. GLB sources, manifests et checksums lorsqu'ils deviennent des sources consommées par le jeu, plus export et conventions compatibles avec les outils Atelier existants. Collision simple de circulation distincte de la décoration, portes libres, LOD et budgets documentés.
5. Rendus de contrôle : extérieurs de profil et trois-quarts laissant voir l'intérieur vide, restaurant dans les deux sens, cabine vers fenêtre et vers couloir, vue de dessus sans toit. Fonds blancs et lumière lisible pour les références techniques.
6. Vérification des dimensions, passage continu, alignement des fenêtres, épaisseur et normales des murs, volumes d'accueil des meubles, accès aux portes et absence d'obstacles. Ne laisse aucun éditeur ou rendu de test ouvert inutilement.

Avance sur cette construction Blender de manière autonome. Ne fusionne pas la carte de Haras Valley, ne place pas de ligne ferroviaire et ne lance pas de génération Tripo : nous gérons les assets Studio séparément. Avant toute intégration Unreal, livre les sources et les vues de contrôle avec les limites restantes clairement indiquées. Résume les modifications et les vérifications pour que les objets Studio puissent être assemblés sur cette coque.
