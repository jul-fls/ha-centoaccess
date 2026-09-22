# CentoAccess

Intégration Home Assistant non officielle pour les informations communales publiées dans l'application mobile CentoAccess : panneau d'affichage, agenda, actualités et informations pratiques.

## Installation

Ajoutez `https://github.com/jul-fls/ha-centoaccess` comme **dépôt personnalisé HACS de type Integration**, installez **CentoAccess**, puis redémarrez Home Assistant. Pour une installation manuelle, copiez `custom_components/centoaccess` dans le dossier `custom_components` de Home Assistant.

Dans **Paramètres > Appareils et services > Ajouter une intégration**, recherchez **CentoAccess**.

## Configuration

Le formulaire propose les mêmes méthodes de localisation que HydroTarif :

- position configurée dans Home Assistant ;
- coordonnées GPS ;
- préfixe de code postal de 2 à 5 chiffres, puis choix de la commune ;
- adresse complète ;
- code INSEE de la commune.

La localisation est d'abord résolue avec l'[API Découpage administratif](https://geo.api.gouv.fr/decoupage-administratif/communes) ou le [géocodeur IGN](https://cartes.gouv.fr/aide/fr/guides-utilisateur/utiliser-les-services-de-la-geoplateforme/geocodage/). L'intégration cherche ensuite une correspondance exacte dans le catalogue CentoAccess. Les préfixes municipaux tels que « Ville de », « Mairie de » ou « Commune de » sont tolérés, mais une commune voisine utilisant le même code postal n'est jamais sélectionnée automatiquement.

Si la commune existe mais n'utilise pas CentoAccess, le formulaire indique explicitement que l'intégration ne peut pas être configurée pour cette commune. Le `panel_id` n'est jamais demandé : il est découvert automatiquement depuis les tuiles publiées par la commune.

Exemple vérifié : le préfixe `33`, puis le choix `33640 - Castres-Gironde`, retrouve l'application **CASTRES-GIRONDE** sans confondre Beautiran ou Portets. La sélection est enregistrée avec l'identifiant stable de l'application CentoAccess, pas avec son libellé.

## Entités

- **Commune** : nom, identifiant CentoAccess, code postal, tuiles publiées et identifiant du panneau.
- **Diapositives du panneau** : nombre de diapositives actives ; l'attribut `slides` contient les messages dédupliqués, leurs cadres, médias et plages de publication.
- **Éléments de l'agenda** : nombre d'événements et détails dans l'attribut `items`.
- **Actualités** : nombre d'actualités et détails dans l'attribut `items`.
- **Informations pratiques** : nombre de fiches ; fiches et liens associés dans les attributs `items` et `links`.
- **Agenda** : calendrier Home Assistant natif utilisable dans les tableaux de bord et automatisations.

Les données sont actualisées toutes les dix minutes. Les URL relatives des images et vidéos sont converties en URL publiques complètes.

## Automatisations

Exemple de notification lorsqu'une nouvelle actualité est publiée :

```yaml
automation:
  - alias: "Nouvelle actualité CentoAccess"
    triggers:
      - trigger: state
        entity_id: sensor.centoaccess_actualites
    conditions:
      - condition: template
        value_template: "{{ trigger.to_state.state | int(0) > trigger.from_state.state | int(0) }}"
    actions:
      - action: notify.notify
        data:
          message: "Une nouvelle actualité a été publiée par la commune."
```

Les identifiants d'entités dépendent du nom de la commune et peuvent être adaptés depuis l'interface Home Assistant.

## Limites et confidentialité

L'intégration expose uniquement des données publiques déjà servies à l'application mobile et au panneau web CentoAccess. Elle utilise le compte de service en lecture seule distribué dans l'application officielle ; aucun compte utilisateur n'est demandé ou stocké. Une modification de l'API privée CentoAccess peut nécessiter une mise à jour de l'intégration.

Ce projet n'est affilié ni à Centaure-Systems ni à Home Assistant.

## Développement et publication

Chaque modification publiée incrémente la version dans `custom_components/centoaccess/manifest.json`. La CI reprend la structure de `ha-hydrotarif` et lance les tests unitaires, Hassfest et la validation HACS à chaque push et pull request.

Les releases GitHub sont créées manuellement après validation de la CI. Un tag doit être au format `vX.Y.Z` et correspondre exactement à la version du manifest. Le script `python scripts/check_version.py` contrôle cette règle ; la CI vérifie aussi automatiquement `RELEASE_TAG` lorsqu'elle s'exécute sur un tag.
