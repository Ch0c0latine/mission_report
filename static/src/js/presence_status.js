/**
 * Badge de présence : rendu d'une saisie d'activité.
 *
 * hr_holidays traite toute saisie en cours comme un congé : icône avion, teinte
 * orangée d'absence, et libellé "..., de retour le ...". Pour une mission, le
 * salarié travaille : on affiche une icône de saisie, du vert, et une fin
 * d'activité plutôt qu'un retour.
 *
 * L'icône, la couleur et le libellé sont calculés en JavaScript par les
 * composants d'hr et d'hr_holidays : ni la vue ni le libellé du champ ne
 * peuvent les atteindre, d'où ce patch. Il ne porte que sur notre propre valeur
 * de hr_icon_display ; tout le reste est délégué à hr_holidays, y compris les
 * vrais congés.
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

function activityLabel(record) {
    // activity_date_to est le dernier jour de la saisie, alors que le
    // leave_date_to d'hr_holidays est le jour de reprise du travail.
    const dateTo = record.data.activity_date_to;
    if (!dateTo) {
        return _t("Activité");
    }
    return _t("Activité, jusqu'au %(date)s", {
        date: dateTo.toLocaleString({ day: "numeric", month: "short", year: "numeric" }),
    });
}

const activityPatch = () => ({
    get icon() {
        return this.value === ACTIVITY ? "fa-pencil-square-o" : super.icon;
    },
    get color() {
        return this.value === ACTIVITY ? "text-success" : super.color;
    },
    get label() {
        return this.value === ACTIVITY ? activityLabel(this.props.record) : super.label;
    },
});

// Les variantes "pill" redéfinissent la couleur en classes de bouton.
const activityPillPatch = () => ({
    get color() {
        return this.value === ACTIVITY ? "btn-outline-success" : super.color;
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
