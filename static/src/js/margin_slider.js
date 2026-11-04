/**
 * Curseur de la marge voulue d'un calcul de marge : de 10 à 40 %.
 *
 * Le tarif journalier suit la marge à chaque déplacement du curseur (au relâchement, pour ne
 * pas recalculer à chaque pixel).
 */
import { Component, useState } from "@odoo/owl";
import { registry } from "@web/core/registry";
import { _t } from "@web/core/l10n/translation";
import { standardFieldProps } from "@web/views/fields/standard_field_props";

export class MarginSliderField extends Component {
    static template = "mission_report.MarginSliderField";
    static props = {
        ...standardFieldProps,
        min: { type: Number, optional: true },
        max: { type: Number, optional: true },
    };
    static defaultProps = { min: 10, max: 40 };

    setup() {
        this.state = useState({ shown: null });
        this.pending = null;
        this.busy = false;
    }

    get value() {
        return this.state.shown !== null ? this.state.shown : this.props.record.data[this.props.name] || 0;
    }

    /** The rate typed by hand gives its own margin: said next to the cursor. */
    get actualLabel() {
        const rate = (this.props.record.data.margin_rate || 0) * 100;
        return `${_t("actual margin")} ${rate.toFixed(1)} %`;
    }

    /** Daily rate that gives the margin, as the server computes it: rounded up to 5. */
    rateFor(percent) {
        const data = this.props.record.data;
        const cost = data.cost_per_day || 0;
        if (!cost || percent >= 100) {
            return null;
        }
        const rate = cost / (1 - percent / 100) - (data.rebilled_total || 0);
        return Math.ceil(Math.max(rate, 0) / 5) * 5;
    }

    /**
     * The daily rate and the margins follow the cursor while it moves: each step is sent at once,
     * one at a time (the steps made meanwhile are merged into the last one).
     */
    async onInput(ev) {
        this.state.shown = parseInt(ev.target.value, 10);
        this.pending = this.state.shown;
        if (this.busy) {
            return;
        }
        this.busy = true;
        try {
            while (this.pending !== null) {
                const percent = this.pending;
                this.pending = null;
                const changes = { [this.props.name]: percent };
                const rate = this.rateFor(percent);
                if (rate !== null) {
                    changes.daily_rate = rate;
                    changes.rate_manual = false;
                }
                await this.props.record.update(changes);
            }
        } finally {
            this.busy = false;
            this.state.shown = null;
        }
    }
}

export const marginSliderField = {
    component: MarginSliderField,
    displayName: "Margin slider",
    supportedTypes: ["integer"],
    extractProps: ({ options }) => ({
        min: options.min,
        max: options.max,
    }),
};

registry.category("fields").add("margin_slider", marginSliderField);
