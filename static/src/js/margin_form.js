/**
 * Formulaire d'un calcul de marge : à l'enregistrement, si le calcul s'écarte de la commande, l'utilisateur choisit.
 *
 * Rien n'est écrit dans la commande tout seul : garder le calcul (l'écart reste affiché), rétablir les conditions de
 * la commande, ou les enregistrer dans la commande, avec une note qui dit pourquoi.
 */
import { Component } from "@odoo/owl";
import { registry } from "@web/core/registry";
import { _t } from "@web/core/l10n/translation";
import { useService } from "@web/core/utils/hooks";
import { Dialog } from "@web/core/dialog/dialog";
import { formView } from "@web/views/form/form_view";
import { FormController } from "@web/views/form/form_controller";

export class MarginGapDialog extends Component {
    static template = "mission_report.MarginGapDialog";
    static components = { Dialog };
    static props = {
        text: String,
        choose: Function,
        close: Function,
    };

    get title() {
        return _t("The calculation differs from the order");
    }

    pick(choice) {
        this.props.choose(choice);
        this.props.close();
    }
}

export class MarginFormController extends FormController {
    setup() {
        super.setup();
        this.dialogService = useService("dialog");
    }

    /** Asks what to do with the gap; null when the dialog is closed without a choice. */
    askGap(text) {
        return new Promise((resolve) => {
            let chosen = null;
            this.dialogService.add(
                MarginGapDialog,
                { text, choose: (choice) => (chosen = choice), close: () => {} },
                { onClose: () => resolve(chosen) }
            );
        });
    }

    async save(params) {
        const root = this.model.root;
        if (root.data.order_gap && root.dirty && !params?.skipGapDialog) {
            const choice = await this.askGap(root.data.order_gap_text);
            if (!choice) {
                return false;
            }
            if (choice === "restore") {
                const field = root.data.billing_mode === "forfait" ? "fixed_price" : "daily_rate";
                await root.update({ [field]: root.data.order_price });
            }
            const saved = await super.save(params);
            if (choice === "record" && saved !== false) {
                const action = await this.orm.call("mission.margin", "action_open_conditions_wizard", [
                    [root.resId],
                ]);
                await this.actionService.doAction(action, { onClose: () => this.model.load() });
            }
            return saved;
        }
        return super.save(params);
    }
}

registry.category("views").add("mission_margin_form", {
    ...formView,
    Controller: MarginFormController,
});
