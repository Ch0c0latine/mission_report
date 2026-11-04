/**
 * Curseur de la marge voulue d'un calcul de marge : de 10 à 40 %.
 *
 * Le tarif journalier suit la marge à chaque déplacement du curseur (au relâchement, pour ne
 * pas recalculer à chaque pixel).
 */
import { Component, useState } from "@odoo/owl";
import { registry } from "@web/core/registry";
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
    }

    get value() {
        return this.state.shown !== null ? this.state.shown : this.props.record.data[this.props.name] || 0;
    }

    onInput(ev) {
        this.state.shown = parseInt(ev.target.value, 10);
    }

    async onChange(ev) {
        const value = parseInt(ev.target.value, 10);
        this.state.shown = null;
        await this.props.record.update({ [this.props.name]: value });
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
