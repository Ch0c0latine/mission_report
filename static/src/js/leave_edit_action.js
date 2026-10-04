/**
 * « Modifier » dans la fenêtre d'une saisie du calendrier : la fiche complète de la saisie
 * s'ouvre dans une fenêtre, et le calendrier se relit à sa fermeture (overview_calendar.js
 * écoute le bus ci-dessous).
 *
 * Boutons de cette fenêtre (contexte mission_edit), plus sobres que ceux d'hr_holidays :
 * - pas de « Refuser » : refuser se fait depuis la fenêtre à ruban du calendrier ;
 * - « Enregistrer » seulement pour une saisie en attente d'approbation ; une saisie approuvée
 *   rouverte pour modification (mission_reopened) s'enregistre par « Approuver », et retrouve
 *   son approbation si la fenêtre se ferme sans cela ;
 * - « Supprimer » aussi pour une saisie refusée ou annulée (hr_holidays ne l'offrait qu'au
 *   propriétaire d'une saisie en attente), avec confirmation ; « Annuler la saisie » reste
 *   pour une saisie approuvée.
 */
import { EventBus } from "@odoo/owl";
import { ConfirmationDialog } from "@web/core/confirmation_dialog/confirmation_dialog";
import { registry } from "@web/core/registry";
import { patch } from "@web/core/utils/patch";

import {
    TimeOffDialogFormController,
    TimeOffFormViewDialog,
} from "@hr_holidays/views/view_dialog/form_view_dialog";

export const missionBus = new EventBus();

const DELETABLE = ["draft", "confirm", "refuse", "cancel"];

patch(TimeOffDialogFormController.prototype, {
    get isMissionEdit() {
        return Boolean(this.props.context?.mission_edit);
    },

    get canRefuse() {
        return super.canRefuse && !this.isMissionEdit;
    },

    get canSave() {
        if (!this.isMissionEdit) {
            return super.canSave;
        }
        const record = this.record;
        return (
            this.hasNoWarning &&
            !this.props.context?.mission_reopened &&
            !record.isNew &&
            record.data.state === "confirm" &&
            record.dirty
        );
    },

    get canDelete() {
        if (!this.isMissionEdit) {
            return super.canDelete;
        }
        return !this.record.isNew && DELETABLE.includes(this.record.data.state);
    },

    // Ici « Annuler la saisie » n'est que l'assistant d'annulation ; la suppression, elle,
    // passe par onRecordDeleted (hr_holidays appelait l'une depuis l'autre).
    cancelRecord() {
        if (!this.isMissionEdit) {
            return super.cancelRecord(...arguments);
        }
        this.leaveCancelWizard(this.record.resId, () => this.props.onLeaveCancelled());
    },
});

registry.category("actions").add("mission_report.edit_leave", (env, action) => {
    const reload = () => missionBus.trigger("reload");
    const orm = env.services.orm;
    return new Promise((resolve) => {
        const close = env.services.dialog.add(
            TimeOffFormViewDialog,
            {
                resModel: "hr.leave",
                resId: action.params.leave_id,
                title: "Saisie",
                context: {
                    form_view_ref: "hr_holidays.hr_leave_view_form",
                    mission_edit: true,
                    mission_reopened: Boolean(action.params.reopened),
                },
                size: "md",
                onRecordSaved: reload,
                onCancelLeave: () => {},
                onRecordDeleted: (record) => {
                    // hr_holidays délègue la suppression au calendrier : ici, avec confirmation.
                    env.services.dialog.add(ConfirmationDialog, {
                        title: "Supprimer la saisie",
                        body: "Supprimer définitivement cette saisie ?",
                        confirmLabel: "Supprimer",
                        confirm: async () => {
                            await orm.unlink("hr.leave", [record.resId]);
                            close();
                        },
                        cancel: () => {},
                    });
                },
                onLeaveCancelled: reload,
            },
            {
                onClose: async () => {
                    if (action.params.reopened) {
                        await orm.call("hr.leave", "action_mission_restore", [[action.params.leave_id]]);
                    }
                    reload();
                    resolve();
                },
            }
        );
    });
});
