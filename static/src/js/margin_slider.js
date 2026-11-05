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
import { formatMonetary } from "@web/views/fields/formatters";

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
        if (this.state.shown !== null) {
            return this.state.shown;
        }
        const data = this.props.record.data;
        // A daily rate typed by hand: the cursor shows the margin it gives.
        if (data.rate_manual && data.margin_rate) {
            return Math.min(Math.max(Math.round(data.margin_rate * 100), this.props.min), this.props.max);
        }
        return data[this.props.name] || 0;
    }

    get label() {
        return this.props.record.fields[this.props.name].string;
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


/**
 * Curseur du salaire brut annuel : du minimum légal de la société (Paramètres) à son maximum.
 *
 * Chaque pas est envoyé tout de suite, un à la fois : le tarif journalier suit le salaire. Le montant exact
 * se saisit dans le champ situé dessous.
 */
export class SalarySliderField extends Component {
    static template = "mission_report.SalarySliderField";
    static props = { ...standardFieldProps };

    setup() {
        this.state = useState({ shown: null });
        this.pending = null;
        this.busy = false;
    }

    get min() {
        return Math.floor(this.props.record.data.salary_min || 20000);
    }

    get max() {
        return Math.ceil(this.props.record.data.salary_max || 80000);
    }

    get step() {
        return 500;
    }

    get label() {
        return this.props.record.fields[this.props.name].string;
    }

    /** The cursor moves by steps of 500 from round numbers: the first notch is the minimum wage itself. */
    get sliderMin() {
        return Math.floor(this.min / this.step) * this.step;
    }

    get sliderMax() {
        return Math.ceil(this.max / this.step) * this.step;
    }

    get value() {
        const value = this.state.shown !== null ? this.state.shown : this.props.record.data[this.props.name] || 0;
        return Math.min(Math.max(value, this.sliderMin), this.sliderMax);
    }

    format(amount) {
        return Math.round(amount).toLocaleString((document.documentElement.lang || "fr").replace("_", "-"));
    }

    async onInput(ev) {
        this.state.shown = Math.min(Math.max(parseInt(ev.target.value, 10), this.min), this.max);
        this.pending = this.state.shown;
        if (this.busy) {
            return;
        }
        this.busy = true;
        try {
            while (this.pending !== null) {
                const amount = this.pending;
                this.pending = null;
                await this.props.record.update({ [this.props.name]: amount });
            }
        } finally {
            this.busy = false;
            this.state.shown = null;
        }
    }
}

export const salarySliderField = {
    component: SalarySliderField,
    displayName: "Salary slider",
    supportedTypes: ["monetary", "float"],
};

registry.category("fields").add("salary_slider", salarySliderField);


/**
 * Curseur du tarif journalier (TJM), de la moitié du coût d'une journée jusqu'à plus de deux fois ce coût, par pas
 * de 5 €. Le déplacer fixe le tarif à la main : le curseur de la marge rend la main à la marge.
 */
export class RateSliderField extends SalarySliderField {
    static template = "mission_report.SalarySliderField";

    get step() {
        return 5;
    }

    get min() {
        const data = this.props.record.data;
        const low = Math.floor(((data.cost_per_day || 0) * 0.5) / 10) * 10;
        const current = Math.floor((data[this.props.name] || 0) / 10) * 10 - 50;
        return Math.max(Math.min(low, current > 0 ? current : low), 0);
    }

    get max() {
        const data = this.props.record.data;
        const high = Math.ceil(Math.max((data.cost_per_day || 0) * 2.2, this.min + 300) / 10) * 10;
        return Math.max(high, Math.ceil((data[this.props.name] || 0) / 10) * 10 + 50);
    }
}

export const rateSliderField = {
    component: RateSliderField,
    displayName: "Daily rate slider",
    supportedTypes: ["monetary", "float"],
};

registry.category("fields").add("rate_slider", rateSliderField);


/**
 * Un tarif journalier indicatif : le montant est un lien, un clic le saisit comme tarif journalier (TJM) de la fiche.
 */
export class RatePickField extends Component {
    static template = "mission_report.RatePickField";
    static props = { ...standardFieldProps };

    get value() {
        return Math.round((this.props.record.data[this.props.name] || 0) * 100) / 100;
    }

    get formatted() {
        const currency = this.props.record.data.currency_id;
        return formatMonetary(this.value, { currencyId: currency && currency.id });
    }

    async onClick(ev) {
        ev.preventDefault();
        if (this.value > 0) {
            await this.props.record.update({ daily_rate: this.value });
        }
    }
}

export const ratePickField = {
    component: RatePickField,
    displayName: "Daily rate to take",
    supportedTypes: ["monetary", "float"],
};

registry.category("fields").add("rate_pick", ratePickField);
