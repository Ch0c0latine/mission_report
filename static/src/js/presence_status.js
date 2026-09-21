/**
 * Badge de présence : rendu d'une saisie de mission.
 *
 * hr_holidays traite toute saisie en cours comme un congé : icône avion, teinte
 * orangée d'absence, et libellé "..., de retour le ...". Pour une mission, le
 * salarié travaille : on affiche une icône d'outil, du vert, et une fin de
 * mission plutôt qu'un retour. Un salarié présent sans mission en cours est
 * signalé comme tel.
 *
 * L'icône, la couleur et le libellé sont calculés en JavaScript par les
 * composants d'hr et d'hr_holidays : ni la vue ni le libellé du champ ne
 * peuvent les atteindre, d'où ce patch. Il ne porte que sur notre propre valeur
 * de hr_icon_display et sur le libellé de la présence simple ; tout le reste est
 * délégué à hr_holidays, y compris les vrais congés.
 *
 * Le dernier patch appliqué est consulté en premier. hr_holidays_homeworking
 * (et hr_homeworking pour le lieu de travail) interceptent notre valeur avant
 * de déléguer : ce fichier doit donc être chargé après eux, ce que garantit la
 * dépendance déclarée dans le manifeste.
 */
import { _t } from "@web/core/l10n/translation";
import { patch } from "@web/core/utils/patch";

import { HrPresenceStatus, hrPresenceStatus } from "@hr/components/hr_presence_status/hr_presence_status";
import {
    HrPresenceStatusPill,
    hrPresenceStatusPill,
} from "@hr/components/hr_presence_status_pill/hr_presence_status_pill";
import {
    HrPresenceStatusPrivate,
    hrPresenceStatusPrivate,
} from "@hr/components/hr_presence_status_private/hr_presence_status_private";
import {
    HrPresenceStatusPrivatePill,
    hrPresenceStatusPrivatePill,
} from "@hr/components/hr_presence_status_private_pill/hr_presence_status_private_pill";

const ACTIVITY = "presence_holiday_activity";
// Présent, sans saisie de mission en cours. Quand un lieu de travail est
// renseigné, hr_homeworking utilise d'autres valeurs (presence_home, ...) et
// garde son propre libellé.
const PRESENT = "presence_present";

/**
 * Libellé propre à ce module, ou undefined pour laisser faire hr_holidays.
 */
function missionLabel(value, record) {
    if (value === ACTIVITY) {
        // activity_date_to est le dernier jour de la saisie, alors que le
        // leave_date_to d'hr_holidays est le jour de reprise du travail.
        const dateTo = record.data.activity_date_to;
        if (!dateTo) {
            return _t("En mission");
        }
        return _t("En mission, jusqu'au %(date)s", {
            date: dateTo.toLocaleString({ day: "numeric", month: "short", year: "numeric" }),
        });
    }
    if (value === PRESENT) {
        return _t("Présent, pas de mission");
    }
}

const activityPatch = () => ({
    get icon() {
        return this.value === ACTIVITY ? "fa-wrench" : super.icon;
    },
    get color() {
        return this.value === ACTIVITY ? "text-success" : super.color;
    },
    get label() {
        return missionLabel(this.value, this.props.record) ?? super.label;
    },
});

// Les variantes "pill" redéfinissent la couleur en classes de bouton. Le
// libellé est aussi redéfini directement sur la variante privée (fiche
// employé), par hr_holidays et hr_holidays_homeworking : celui hérité de
// HrPresenceStatus n'y est donc jamais consulté.
const activityPillPatch = () => ({
    get color() {
        return this.value === ACTIVITY ? "btn-outline-success" : super.color;
    },
    get label() {
        return missionLabel(this.value, this.props.record) ?? super.label;
    },
});

patch(HrPresenceStatus.prototype, activityPatch());
patch(HrPresenceStatusPrivate.prototype, activityPatch());
patch(HrPresenceStatusPill.prototype, activityPillPatch());
patch(HrPresenceStatusPrivatePill.prototype, activityPillPatch());

// Sans cette dépendance, le champ n'est pas chargé avec l'enregistrement et le
// libellé ne peut pas afficher la date.
for (const widget of [
    hrPresenceStatus,
    hrPresenceStatusPrivate,
    hrPresenceStatusPill,
    hrPresenceStatusPrivatePill,
]) {
    widget.fieldDependencies = [
        ...widget.fieldDependencies,
        { name: "activity_date_to", type: "date" },
    ];
}
