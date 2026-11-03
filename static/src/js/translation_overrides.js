/**
 * Renames the labels of hr_holidays that come from its JavaScript code.
 *
 * These strings cannot be reached by view inheritance, nor by a translation
 * file of our module (the translations of code are loaded per module, from the
 * module's own .po file - tested, no effect), nor by template inheritance when
 * they are passed as props from a .js file.
 *
 * So we write directly into the translation catalogue already loaded. No
 * logic of Odoo is copied: should the API change, the labels would simply stay
 * unchanged, without breaking the interface.
 */
import { translatedTerms, translatedTermsGlobal, translationIsReady } from "@web/core/l10n/translation";
import { user } from "@web/core/user";

// Wording of the entry popup, in English and in French (the other languages read the English one).
// - "Time Off Request" / "New Time Off": titles of the popup, passed by
//   hr_holidays/static/src/views/calendar/calendar_controller.js (opening an entry, creating one).
// - "Submit Request" / "Delete Time Off": buttons of the footer, defined in
//   hr_holidays/static/src/views/view_dialog/form_view_dialog.xml.
// - "Cancel Time Off": shown instead of "Delete" once the entry is validated: it does not delete
//   the record, it sets it to cancelled.
const WORDING = {
    en: {
        "Time Off Request": "Entry",
        "New Time Off": "New entry",
        "Submit Request": "Save",
        "Delete Time Off": "Delete",
        "Cancel Time Off": "Cancel the entry",
    },
    fr: {
        "Time Off Request": "Saisie",
        "New Time Off": "Nouvelle saisie",
        "Submit Request": "Enregistrer",
        "Delete Time Off": "Supprimer",
        "Cancel Time Off": "Annuler la saisie",
    },
};
const OVERRIDES = WORDING[(user.lang || "en").slice(0, 2)] || WORDING.en;

translationIsReady.then(() => {
    // The catalogue is indexed by module; the term is replaced wherever it is already
    // translated, without depending on the exact name of the context key.
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
    // Fallback for the contexts where the term is not translated (source language).
    Object.assign(translatedTermsGlobal, OVERRIDES);
});
