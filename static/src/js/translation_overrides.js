/**
 * Renomme les libellés d'hr_holidays qui proviennent de son code JavaScript.
 *
 * Ces chaînes ne sont atteignables ni par l'héritage de vues, ni par un fichier
 * de traduction dans notre module (les traductions de code sont chargées par
 * module, depuis le .po du module lui-même - testé, sans effet), ni par
 * l'héritage de template quand elles sont passées en props depuis un .js.
 *
 * On écrit donc directement dans le catalogue de traductions déjà chargé.
 * Aucune logique d'Odoo n'est copiée : si l'API changeait, les libellés
 * resteraient simplement inchangés, sans casser l'interface.
 */
import { translatedTerms, translatedTermsGlobal, translationIsReady } from "@web/core/l10n/translation";

const OVERRIDES = {
    // Titre du popup de saisie, passé par hr_holidays/static/src/views/calendar/calendar_controller.js
    "Time Off Request": "Saisie d'activité",
};

translationIsReady.then(() => {
    // Le catalogue est indexé par module ; on remplace le terme partout où il
    // est déjà traduit, sans dépendre du nom exact de la clé de contexte.
    for (const context of Object.keys(translatedTerms)) {
        const terms = translatedTerms[context];
        if (!terms || typeof terms !== "object") {
            continue;
        }
        for (const [source, translation] of Object.entries(OVERRIDES)) {
            if (source in terms) {
                terms[source] = translation;
            }
        }
    }
    // Repli pour les contextes où le terme n'est pas traduit (langue source).
    Object.assign(translatedTermsGlobal, OVERRIDES);
});
