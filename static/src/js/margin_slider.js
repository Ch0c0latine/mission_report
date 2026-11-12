/**
 * Les curseurs de la marge et du tarif journalier (TJM) : leurs limites suivent la valeur saisie.
 *
 * Règle commune, pour que les deux curseurs se comportent de la même façon : les limites sont centrées sur la
 * valeur ; elles ne bougent que si la valeur sort de l'intervalle ou entre dans ses 15 % extrêmes, et alors une seule
 * fois, recentrées avec de la marge des deux côtés. Pendant qu'on déplace le curseur, les limites ne reculent jamais ;
 * tout au bout, l'intervalle s'agrandit une fois par déplacement. Au relâchement, un recentrage si la valeur est près
 * d'une limite.
 */
import { Component, useState } from "@odoo/owl";
import { registry } from "@web/core/registry";
import { _t } from "@web/core/l10n/translation";
import { standardFieldProps } from "@web/views/fields/standard_field_props";
import { formatMonetary } from "@web/views/fields/formatters";

const NEAR = 0.15;
const EDGE = 0.04;

/** The limits centred on a value, on steps, inside the absolute limits, with the width kept when one side is cut. */
export function centred(value, half, step, low, high) {
    let lo = Math.floor((value - half) / step) * step;
    let hi = Math.ceil((value + half) / step) * step;
    const width = hi - lo;
    if (lo < low) {
        lo = low;
        hi = Math.min(high, lo + width);
    }
    if (hi > high) {
        hi = high;
        lo = Math.max(low, hi - width);
    }
    return [lo, hi];
}

export class DynamicRange {
    /** @param {{half: function(number): number, step: number, low: number, high: number}} options */
    constructor(options) {
        Object.assign(this, options);
        this.lo = null;
        this.hi = null;
        this.dragging = false;
        this.extended = false;
    }

    /** The limits for a value: recentred only out of the range or in its outer part, never while dragging. */
    bounds(value) {
        if (this.lo === null) {
            [this.lo, this.hi] = centred(value, this.half(value), this.step, this.low, this.high);
        } else if (!this.dragging) {
            const width = this.hi - this.lo;
            if (value < this.lo + NEAR * width || value > this.hi - NEAR * width) {
                [this.lo, this.hi] = centred(value, this.half(value), this.step, this.low, this.high);
            }
        }
        return [this.lo, this.hi];
    }

    dragStart() {
        this.dragging = true;
        this.extended = false;
    }

    dragEnd() {
        this.dragging = false;
        this.extended = false;
    }

    /** At the very end of the range while it is dragged: the range grows once, by half its width. */
    drag(value) {
        if (this.extended || this.lo === null) {
            return;
        }
        const width = this.hi - this.lo;
        const grow = Math.ceil(width / 2 / this.step) * this.step;
        if (value >= this.hi - EDGE * width && this.hi < this.high) {
            this.hi = Math.min(this.high, this.hi + grow);
            this.extended = true;
        } else if (value <= this.lo + EDGE * width && this.lo > this.low) {
            this.lo = Math.max(this.low, this.lo - grow);
            this.extended = true;
        }
    }
}

/** Curseur de la marge : quelques points autour de la marge saisie, entre 0 et 90 %. */
export class MarginSliderField extends Component {
    static template = "mission_report.MarginSliderField";
    static props = {
        ...standardFieldProps,
        min: { type: Number, optional: true },
        max: { type: Number, optional: true },
    };

    setup() {
        this.state = useState({ shown: null, rev: 0 });
        this.pending = null;
        this.busy = false;
        this.range = new DynamicRange({ half: () => 15, step: 1, low: 0, high: 90 });
    }

    get rawValue() {
        if (this.state.shown !== null) {
            return this.state.shown;
        }
        const data = this.props.record.data;
        // A daily rate typed by hand: the cursor shows the margin it gives.
        if (data.rate_manual && data.margin_rate) {
            return Math.min(Math.max(Math.round(data.margin_rate * 100), 0), 90);
        }
        return Math.min(Math.max(data[this.props.name] || 0, 0), 90);
    }

    get bounds() {
        this.state.rev; // read: the limits are looked at again after a release
        return this.range.bounds(this.rawValue);
    }

    get value() {
        return this.rawValue;
    }

    get label() {
        return this.props.record.fields[this.props.name].string;
    }

    onDragStart() {
        this.range.dragStart();
    }

    onDragEnd() {
        this.range.dragEnd();
        this.state.rev++;
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
        this.range.drag(this.state.shown);
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

    onDragStart() {}

    onDragEnd() {}

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
 * Curseur du tarif journalier (TJM) : par pas de 5 €, avec des limites centrées sur le tarif saisi (la même règle que
 * le curseur de la marge). Le déplacer fixe le tarif à la main : le curseur de la marge suit la marge obtenue.
 */
export class RateSliderField extends SalarySliderField {
    static template = "mission_report.SalarySliderField";

    setup() {
        super.setup();
        this.state.rev = 0;
        this.range = new DynamicRange({
            half: (value) => Math.max(100, Math.round((0.3 * Math.abs(value)) / 10) * 10),
            step: 5,
            low: 0,
            high: 10000,
        });
    }

    get step() {
        return 5;
    }

    get rawValue() {
        return this.state.shown !== null ? this.state.shown : this.props.record.data[this.props.name] || 0;
    }

    get bounds() {
        this.state.rev; // read: the limits are looked at again after a release
        return this.range.bounds(this.rawValue);
    }

    get min() {
        return this.bounds[0];
    }

    get max() {
        return this.bounds[1];
    }

    get sliderMin() {
        return this.bounds[0];
    }

    get sliderMax() {
        return this.bounds[1];
    }

    onDragStart() {
        this.range.dragStart();
    }

    onDragEnd() {
        this.range.dragEnd();
        this.state.rev++;
    }

    async onInput(ev) {
        this.range.drag(parseInt(ev.target.value, 10));
        return super.onInput(ev);
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
