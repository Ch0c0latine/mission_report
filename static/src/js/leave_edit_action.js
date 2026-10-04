/**
 * « Modifier » dans la fenêtre d'une saisie du calendrier : la fiche complète de la saisie
 * s'ouvre dans une fenêtre, et le calendrier se relit à sa fermeture (overview_calendar.js
 * écoute le bus ci-dessous).
 */
import { EventBus } from "@odoo/owl";
import { registry } from "@web/core/registry";

import { TimeOffFormViewDialog } from "@hr_holidays/views/view_dialog/form_view_dialog";

export const missionBus = new EventBus();

registry.category("actions").add("mission_report.edit_leave", (env, action) => {
    const reload = () => missionBus.trigger("reload");
    return new Promise((resolve) => {
        env.services.dialog.add(
            TimeOffFormViewDialog,
            {
                resModel: "hr.leave",
                resId: action.params.leave_id,
                title: "Saisie",
                context: { form_view_ref: "hr_holidays.hr_leave_view_form" },
                size: "md",
                onRecordSaved: reload,
                onRecordDeleted: reload,
                onLeaveCancelled: reload,
            },
            {
                onClose: () => {
                    reload();
                    resolve();
                },
            }
        );
    });
});
